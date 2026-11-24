#include "channel.h"
#include "configuration.h"
#include "nvs.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <inttypes.h>
#include <stdatomic.h>

typedef struct {
    uint32_t configTag, token;
    uint8_t active, pending;
} SavedChannel;
typedef struct { unsigned channel; uint32_t token; } Request;
enum Stage { IDLE, VERIFYING, CONFIRMING };
static SavedChannel saved;
static nvs_handle_t storage;
static QueueHandle_t requests;
static atomic_bool busy;
static enum Stage stage;
static uint32_t transaction;
static uint8_t target, tuned;
static int64_t started, lastTx;

static void persist(void)
{
    ESP_ERROR_CHECK(nvs_set_blob(storage, "state", &saved, sizeof(saved)));
    ESP_ERROR_CHECK(nvs_commit(storage));
}

static void tune(uint8_t ch)
{
    if (tuned != ch) { linkTune(ch); tuned = ch; }
}

static void sendControl(uint8_t kind, uint32_t token, uint8_t destination)
{
    LinkPacket p = linkPacket(kind, token, 1);
    p.x = tuned;
    p.y = destination;
    linkSend(&p); // Each management step is retransmitted until its deadline or acknowledgement.
}

static void result(const char *status)
{
    stationMessage("CHANNEL %08" PRIx32 " %s %u\n", transaction, status, saved.active);
}

static void receiverStep(const LinkPacket *p, int64_t now)
{
    if (p->x != tuned) return;
    if (stage == VERIFYING && p->kind == CH_PROOF && p->session == transaction &&
        tuned == target && p->y == target) {
        // The handheld has answered a challenge on the new channel. It has already
        // journaled both channels and can find this durable decision after a reboot.
        saved.active = target;
        persist();
        stage = CONFIRMING;
        started = now;
        sendControl(CH_HERE, transaction, saved.active);
    } else if (stage == CONFIRMING && p->kind == CH_DONE && p->session == transaction && tuned == saved.active) {
        result("OK"); stage = IDLE; busy = false;
    } else if (stage != VERIFYING && p->kind == CH_WHERE && tuned == saved.active) {
        sendControl(CH_HERE, p->session, saved.active);
    }
}

static void senderStep(const LinkPacket *p, int64_t now)
{
    if (p->x != tuned || p->y < 1 || p->y > 11) return;
    if (!saved.pending && p->kind == CH_OFFER && tuned == saved.active) {
        saved.pending = p->y; saved.token = p->session;
        persist();
        busy = true; started = now; lastTx = 0;
        tune(saved.pending);
    } else if (saved.pending && p->session == saved.token && p->kind == CH_VERIFY && tuned == saved.pending) {
        sendControl(CH_PROOF, saved.token, tuned);
    } else if (p->kind == CH_HERE && p->y == tuned) {
        if (saved.pending && p->session == saved.token && (tuned == saved.pending || tuned == saved.active)) {
            saved.active = tuned; saved.pending = 0; saved.token = 0;
            persist(); busy = false;
        }
        if (!saved.pending && tuned == saved.active) sendControl(CH_DONE, p->session, tuned);
    }
}

static void tick(int64_t now)
{
    if (linkRole() == ROLE_HANDHELD) {
        if (!saved.pending) return;
        // Start on the candidate. Recovery checks just the two journaled channels.
        int64_t elapsed = now - started;
        bool previous = elapsed >= 1500 && ((elapsed - 1500) / 450) % 2 == 0;
        tune(previous ? saved.active : saved.pending);
        if (now - lastTx >= 65) { sendControl(CH_WHERE, saved.token, tuned); lastTx = now; }
        return;
    }
    if (stage == IDLE) return;
    if (now - started >= 6500) {
        tune(saved.active);
        result(stage == VERIFYING ? "ROLLED_BACK" : "COMMITTED_UNCONFIRMED");
        stage = IDLE; busy = false; return;
    }
    if (stage == VERIFYING) {
        bool offer = (now - started) % 850 < 300;
        tune(offer ? saved.active : target);
        if (now - lastTx >= 55) { sendControl(offer ? CH_OFFER : CH_VERIFY, transaction, target); lastTx = now; }
    } else if (now - lastTx >= 65) {
        sendControl(CH_HERE, transaction, saved.active); lastTx = now;
    }
}

static void channelTask(void *arg)
{
    for (;;) {
        int64_t now = esp_timer_get_time() / 1000;
        bool configuring = configurationTick(now);
        if (configurationNeedsChannelSync()) {
            saved = (SavedChannel){.configTag=linkConfigTag(), .active=linkDefaultChannel()};
            tuned=saved.active;stage=IDLE;busy=false;persist();
        }
        if (configuring) {
            Request rejected;
            while (xQueueReceive(requests,&rejected,0))
                stationMessage("CHANNEL %08" PRIx32 " BUSY %u\n",rejected.token,saved.active);
            vTaskDelay(pdMS_TO_TICKS(5)); continue;
        }
        Request req;
        if (xQueueReceive(requests, &req, 0)) {
            if (req.channel == 0) stationMessage("CHANNEL %08" PRIx32 " CURRENT %u\n", req.token, saved.active);
            else if (stage != IDLE) stationMessage("CHANNEL %08" PRIx32 " BUSY %u\n", req.token, saved.active);
            else {
                transaction = req.token; target = req.channel; started = now; lastTx = 0;
                stage = VERIFYING; busy = true;
            }
        }
        LinkPacket p;
        while (linkManagement(&p)) {
            if (linkRole() == ROLE_STATION) receiverStep(&p, now);
            else senderStep(&p, now);
        }
        tick(now);
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

bool channelBusy(void) { return atomic_load(&busy); }
uint8_t channelCurrent(void) { return saved.active; }

void channelCommand(unsigned ch, uint32_t token)
{
    if (configurationBusy()) {
        stationMessage("CHANNEL %08" PRIx32 " BUSY %u\n", token, saved.active);return;
    }
    Request req = {ch, token};
    if (ch > 11 || !token || !xQueueSend(requests, &req, 0))
        stationMessage("CHANNEL %08" PRIx32 " REJECTED 0\n", token);
}

void channelStart(void)
{
    ESP_ERROR_CHECK(nvs_open("remote_radio", NVS_READWRITE, &storage));
    size_t size = sizeof(saved);
    esp_err_t read = nvs_get_blob(storage, "state", &saved, &size);
    if (read != ESP_OK && read != ESP_ERR_NVS_NOT_FOUND) ESP_ERROR_CHECK(read);
    if (read != ESP_OK || size != sizeof(saved) || saved.configTag != linkConfigTag() ||
        !saved.active || saved.active > 11 || saved.pending > 11)
        saved = (SavedChannel){.configTag=linkConfigTag(), .active=linkDefaultChannel()};
    tune(saved.pending ? saved.pending : saved.active);
    ESP_LOGI("channel", "Saved channel %u, pending %u", saved.active, saved.pending);
    busy = saved.pending != 0; started = esp_timer_get_time() / 1000;
    requests = xQueueCreate(2, sizeof(Request));
    configASSERT(requests);
    BaseType_t ok = xTaskCreate(channelTask, "channel", 8192, NULL, 4, NULL);
    configASSERT(ok == pdPASS);
}
