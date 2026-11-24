#include <string.h>
#include "board.h"
#include "controls.h"
#include "link.h"
#include "usb.h"
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdatomic.h>
#include "channel.h"
#include "configuration.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/queue.h"
#include "freertos/task.h"

typedef struct { int16_t x, y; } Motion;
static QueueHandle_t presses, moves;
static _Atomic uint16_t battery;
static atomic_bool transmitting;
static uint16_t startupKeys;
static uint32_t session, seq;

// Summarise local motion after AIM ends; never print in the per-report send path.
static void logAimMotion(bool aim, const Motion *motion)
{
    static bool wasAiming;
    static uint32_t reports;
    static int16_t minX, maxX, minY, maxY;
    if (!consoleConnected()) { wasAiming = false; return; }
    if (aim && !wasAiming) {
        reports = 0;
        minX = maxX = minY = maxY = 0;
    }
    if (aim && motion) {
        ++reports;
        if (motion->x < minX) minX = motion->x;
        if (motion->x > maxX) maxX = motion->x;
        if (motion->y < minY) minY = motion->y;
        if (motion->y > maxY) maxY = motion->y;
    }
    if (!aim && wasAiming) {
        ESP_LOGI("motion", "Local AIM: %" PRIu32 " movement reports, dx=[%d,%d] dy=[%d,%d]",
                 reports, minX, maxX, minY, maxY);
    }
    wasAiming = aim;
}

// USB-only diagnostics include S9 MODE, reserved without an assigned action.
static void logMatrixKeys(uint16_t raw, int64_t now)
{
    static uint16_t candidate, stable;
    static int64_t changed;
    static const char *const names[] = {
        "BACK", "UP", "HOME", "LEFT", "OK", "RIGHT", "AIM", "DOWN", "MODE"
    };
    if (linkProfile() != PROFILE_MATRIX || !consoleConnected()) {
        candidate = stable = 0;
        changed = now;
        return;
    }
    raw &= 0x1ff;
    if (raw != candidate) { candidate = raw; changed = now; }
    if (raw == stable || now - changed < 8000) return;
    uint16_t edges = raw ^ stable;
    for (unsigned i = 0; i < 9; ++i) {
        if (edges & (1u << i)) {
            ESP_LOGI("buttons", "S%u %s (%s, row%u col%u)", i + 1,
                     raw & (1u << i) ? "PRESSED" : "RELEASED", names[i], i / 3 + 1, i % 3 + 1);
        }
    }
    stable = raw;
}

static void applyKeys(ButtonActions a)
{
    if (a.calibrate) startStaffCalibration();
    if (a.sensitivity) cycleSensitivity();
    for (uint8_t i = 0; i < 8; i++) {
        if (!(a.forward & (1u << i))) continue;
        if (xQueueSend(presses, &i, 0) != pdTRUE) ESP_LOGW("keys", "Input queue full");
    }
}

static void inputs(void *arg)
{
    controlsInit();
    if (esp_reset_reason() == ESP_RST_DEEPSLEEP)
        ESP_LOGI("power", "Woke from deep sleep (wake cause=%d)", esp_sleep_get_wakeup_cause());
    if (linkProfile() == PROFILE_MATRIX)
        ESP_LOGI("power", "Idle deep sleep after %u seconds, including on USB", IDLE_SLEEP_SECONDS);
    if (linkProfile() == PROFILE_MATRIX && consoleConnected()) {
        ESP_LOGI("buttons", "Matrix ready: rows GPIO%d/%d/%d, columns GPIO%d/%d/%d",
                 ROW1, ROW2, ROW3, COL1, COL2, COL3);
        ESP_LOGI("buttons", "S1 BACK | S2 UP | S3 HOME | S4 LEFT | S5 OK | S6 RIGHT | S7 AIM | S8 DOWN | S9 MODE (reserved)");
    }
    uint16_t stable = startupKeys, candidate = stable;
    bool chord = false;
    ButtonActions actions = buttonActions(0, stable & 0xff, &chord);
    applyKeys(actions);
    int64_t changed = esp_timer_get_time(), nextBattery = 0;
    int64_t active = changed;
    updateStatusLed(stable != 0, actions.aim, changed);
    int64_t setupHeld = 0;
    bool setupRequested = false;
    for (;;) {
        int64_t now = esp_timer_get_time();
        uint16_t raw = matrixScan();
        logMatrixKeys(raw, now);
        const uint16_t setupChord = (1u << KEY_AIM_INDEX) | (1u << KEY_MODE_INDEX);
        bool setupKeys = linkProfile()==PROFILE_MATRIX && (raw & setupChord)==setupChord;
        if (!setupKeys) { setupHeld=0;setupRequested=false; }
        else if (!setupHeld) setupHeld=now;
        if (setupKeys && !setupRequested && now-setupHeld>=3000000) {
            configurationEnterSpare();setupRequested=true;
        }
        if (setupKeys || configurationBusy()) {
            active=now;stable=candidate=0;actions=(ButtonActions){0};chord=false;
            xQueueReset(moves);xQueueReset(presses);
            int16_t unusedX,unusedY;readMotion(false,true,&unusedX,&unusedY);
            if(!configurationLed(now)) updateStatusLed(false,false,now);
            vTaskDelay(pdMS_TO_TICKS(2));continue;
        }
        uint16_t sample = raw & 0x1ff;  // S9 has press feedback and wakes/keeps the sender awake.
        bool buttonPressed = false;
        if (sample != candidate) { candidate = sample; changed = now; }
        if (sample != stable && now - changed >= 8000) {
            bool wasAiming = actions.aim;
            buttonPressed = (sample & ~stable) != 0;
            // S9 remains reserved for application actions; AIM+S9 setup is handled above.
            actions = buttonActions(stable & 0xff, sample & 0xff, &chord);
            applyKeys(actions);
            if (actions.aim != wasAiming) ESP_LOGI("inputs", "AIM %s", actions.aim ? "held" : "released");
            if (!actions.aim) xQueueReset(moves);
            stable = sample;
        }
        if (sample || channelBusy() || transmitting) active = now;
        if (now >= nextBattery) {
            battery = batteryMillivolts();
            nextBattery = now + 5000000;
        }
        Motion m;
        bool haveMotion = readMotion(actions.aim, stable != 0, &m.x, &m.y);
        if (haveMotion) xQueueOverwrite(moves, &m);
        logAimMotion(actions.aim, haveMotion ? &m : NULL);
        updateStatusLed(buttonPressed, actions.aim, now);
        if (staffCalibrationActive()) active = now;
        if (linkProfile() == PROFILE_MATRIX && now - active >= (int64_t)IDLE_SLEEP_SECONDS * 1000000 &&
            !sample && !stable && !transmitting && !uxQueueMessagesWaiting(presses) && !channelBusy()) controlsSleep();
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

static LinkPacket newPacket(uint8_t kind)
{
    if (++seq == 0) { session = esp_random() | 1; seq = 1; }
    LinkPacket p = linkPacket(kind, session, seq);
    p.batteryMv = battery;
    return p;
}

// Keep the same event ID on all attempts so the host can discard duplicates.
static int64_t confirmed(LinkPacket *p, unsigned *retries)
{
    int64_t start = esp_timer_get_time();
    for (unsigned attempt = 0; attempt < 3; attempt++) {
        if (attempt) ++*retries;
        if (linkSend(p) != ESP_OK) { vTaskDelay(pdMS_TO_TICKS(1)); continue; }
        int64_t end = esp_timer_get_time() + 50000;
        while (true) {
            int64_t left = end - esp_timer_get_time();
            if (left <= 0) break;
            LinkPacket ack;
            if (linkReceive(&ack, pdMS_TO_TICKS((left + 999) / 1000)) &&
                ack.session == p->session && ack.sequence == p->sequence)
                return esp_timer_get_time() - start;
        }
    }
    return -1;
}

static void burst(unsigned count)
{
    int64_t min = INT64_MAX, max = 0, total = 0;
    unsigned good = 0, retries = 0;
    for (; good < count; good++) {
        LinkPacket p = newPacket(EVENT_TEST);
        int64_t us = confirmed(&p, &retries);
        if (us < 0) { ESP_LOGW("burst", "Timeout at sequence %" PRIu32, p.sequence); break; }
        if (us < min) min = us;
        if (us > max) max = us;
        total += us;
    }
    printf("BURST acked=%u requested=%u retries=%u", good, count, retries);
    if (good) printf(" min_ms=%.3f avg_ms=%.3f max_ms=%.3f", min/1000., total/(1000.*good), max/1000.);
    printf("\n");
    fflush(stdout);
}

void captureWakeKeys(void)
{
    matrixInit();
    uint16_t first = matrixScan();
    vTaskDelay(pdMS_TO_TICKS(8));
    uint16_t second = matrixScan();
    uint16_t setupChord=(1u<<KEY_AIM_INDEX)|(1u<<KEY_MODE_INDEX);
    startupKeys = (second & setupChord)==setupChord ? 0 : first & second & 0x1ff;
}

void runHandheld(void)
{
    usbInit();
    const bool crowd = linkProfile() == PROFILE_CROWD;
    presses = xQueueCreate(32, sizeof(uint8_t));
    moves = xQueueCreate(1, sizeof(Motion));
    assert(presses && moves);
    if (!crowd) {
        BaseType_t started = xTaskCreate(inputs, "inputs", 4096, NULL, 5, NULL);
        assert(started == pdPASS);
    }
    uint32_t good = 0, lost = 0;
    unsigned retriesTotal = 0;
    int64_t nextHello = 0, nextReport = 0;
    session = esp_random() | 1;
    ESP_LOGI("handheld", "Ready. Enter burst 100 to measure acknowledgements.");
    char command[64];
    for (;;) {
        if(configurationBusy()) {vTaskDelay(pdMS_TO_TICKS(5));continue;}
        if (usbLine(command, sizeof(command))) {
            unsigned n; char extra;
            if (sscanf(command, "burst %u %c", &n, &extra) == 1 && n >= 1 && n <= 10000) {
                transmitting = true;
                burst(n);
                transmitting = false;
            }
            else ESP_LOGI("handheld", "Command: burst 1..10000");
        }
        if (crowd && !channelBusy() && esp_timer_get_time() >= nextHello) {
            LinkPacket hello = newPacket(EVENT_TEST);
            memcpy(hello.text, "HELLO", 6);
            if (confirmed(&hello, &retriesTotal) >= 0) ++good;
            else ++lost;
            int64_t now = esp_timer_get_time();
            nextHello = now + (34 + esp_random() % 333) * 1000;
            if (now >= nextReport) {
                ESP_LOGI("crowd", "HELLO acked=%" PRIu32 " failed=%" PRIu32 " retries=%u", good, lost, retriesTotal);
                nextReport = now + 10000000;
            }
        }
        uint8_t key;
        if (xQueueReceive(presses, &key, 0)) {
            LinkPacket p = newPacket(EVENT_KEY);
            p.x = key;
            unsigned retries = 0;
            transmitting = true;
            int64_t us = confirmed(&p, &retries);
            transmitting = false;
            ESP_LOGI("key", "index=%u confirmed_us=%" PRId64 " retries=%u", key, us, retries);
        } else {
            Motion m;
            if (xQueueReceive(moves, &m, pdMS_TO_TICKS(1))) {
                LinkPacket p = newPacket(EVENT_MOVE);
                p.x = m.x; p.y = m.y;
                linkSend(&p);
            }
        }
    }
}
