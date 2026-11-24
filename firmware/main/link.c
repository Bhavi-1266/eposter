#include "link.h"
#include "configuration.h"
#include <string.h>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_crc.h"
#include "nvs.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_partition.h"
#include "esp_wifi.h"
#include "freertos/queue.h"
#include "nvs_flash.h"
#include "freertos/semphr.h"
#include "esp_mac.h"
#include "esp_check.h"

#define WIRE_MAGIC 0x31435250u
_Static_assert(sizeof(LinkPacket) == 20, "wire layout");
static QueueHandle_t rxQueue, managementQueue;
static PairConfig config;
static uint8_t setupKey[16], hardware[6];
static bool haveSetupKey;
static SemaphoreHandle_t radioLock;
static const uint8_t broadcast[6] = {255,255,255,255,255,255};
const uint8_t *linkSetupKey(void) { return setupKey; }
bool linkHasSetupKey(void) { return haveSetupKey; }
void linkHardwareAddress(uint8_t mac[6]) { memcpy(mac, hardware, 6); }
void linkGetConfig(PairConfig *cfg) { *cfg = config; }
uint8_t linkRole(void) { return config.role; }
uint8_t linkProfile(void) { return config.profile; }
uint8_t linkDefaultChannel(void) { return config.channel; }
const char *linkId(void) { return config.id; }
uint32_t linkConfigTag(void) { return esp_crc32_le(0, (uint8_t *)&config, sizeof(config)); }

static void onReceive(const esp_now_recv_info_t *info, const uint8_t *bytes, int length)
{
    if (!info) return;
    if (configurationReceive(info->src_addr, bytes, length)) return;
    if (configurationBusy() || length != sizeof(LinkPacket) || memcmp(info->src_addr, config.peer, 6) ||
        memcmp(info->des_addr, config.local, 6)) return;
    LinkPacket p;
    memcpy(&p, bytes, sizeof(p));
    if (p.magic != WIRE_MAGIC || p.version != 1 || !p.session || !p.sequence) return;
    if (p.kind >= CH_OFFER && p.kind <= CH_DONE) {
        if (info->rx_ctrl && info->rx_ctrl->channel == p.x)
            xQueueSend(managementQueue, &p, 0);
        return;
    }
    if (config.role == ROLE_HANDHELD ? p.kind != EVENT_ACK :
        (p.kind < EVENT_KEY || p.kind > EVENT_TEST)) return;
    xQueueSend(rxQueue, &p, 0);
}

bool linkValidConfig(const PairConfig *cfg)
{
    if (memcmp(cfg->magic, "RCF2", 4) || (cfg->role != ROLE_HANDHELD && cfg->role != ROLE_STATION) ||
        cfg->profile > PROFILE_ONE_BUTTON || cfg->channel < 1 || cfg->channel > 11 ||
        (cfg->local[0] & 3) != 2 || (cfg->peer[0] & 3) != 2 || !cfg->id[0] ||
        !memchr(cfg->id, 0, sizeof(cfg->id)) || !memcmp(cfg->local, cfg->peer, 6)) return false;
    for (unsigned i = 0; cfg->id[i]; ++i) {
        unsigned char c = cfg->id[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
              (i && (c == '_' || c == '-' || c == '.')))) return false;
    }
    return true;
}

esp_err_t linkReadSetup(void)
{
    ESP_RETURN_ON_ERROR(nvs_flash_init(), "link", "NVS init failed");
    const esp_partition_t *part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, "paircfg");
    if (!part || esp_partition_read(part, 0, &config, sizeof(config)) != ESP_OK ||
        !linkValidConfig(&config)) {
        ESP_LOGE("link", "Set data/setup.json and run idf.py flash");
        return ESP_ERR_INVALID_STATE;
    }
    struct { uint8_t magic[4], key[16]; uint32_t crc; } setup = {0};
    haveSetupKey = esp_partition_read(part, 256, &setup, sizeof(setup)) == ESP_OK &&
        !memcmp(setup.magic, "SET1", 4) && setup.crc == esp_crc32_le(0, setup.key, 16);
    if (haveSetupKey) memcpy(setupKey, setup.key, 16);
    ESP_RETURN_ON_ERROR(esp_read_mac(hardware, ESP_MAC_WIFI_STA), "link", "Hardware ID failed");
    uint32_t factoryTag = esp_crc32_le(0, (const uint8_t *)&config, sizeof(config));
    factoryTag = esp_crc32_le(factoryTag, setupKey, sizeof(setupKey));
    return configurationLoad(&config, factoryTag);
}

esp_err_t linkStart(void)
{
    rxQueue = xQueueCreate(16, sizeof(LinkPacket));
    managementQueue = xQueueCreate(12, sizeof(LinkPacket));
    if (!rxQueue || !managementQueue) return ESP_ERR_NO_MEM;
    radioLock = xSemaphoreCreateMutex();
    if (!radioLock) return ESP_ERR_NO_MEM;
    configurationInit();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t wifi = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, config.local));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(config.channel, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk(config.pmk));
    esp_now_peer_info_t peer = { .channel = 0, .ifidx = WIFI_IF_STA, .encrypt = true };
    memcpy(peer.peer_addr, config.peer, 6);
    memcpy(peer.lmk, config.lmk, sizeof(peer.lmk));
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    ESP_ERROR_CHECK(esp_now_register_recv_cb(onReceive));
    ESP_LOGI("link", "Encrypted pair %s", config.id);
    return ESP_OK;
}

void linkTune(uint8_t ch) {
    xSemaphoreTake(radioLock, portMAX_DELAY);
    ESP_ERROR_CHECK(esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE));
    xSemaphoreGive(radioLock);
}
bool linkManagement(LinkPacket *p) { return xQueueReceive(managementQueue, p, 0) == pdTRUE; }

LinkPacket linkPacket(uint8_t kind, uint32_t session, uint32_t sequence)
{
    return (LinkPacket){.magic=WIRE_MAGIC, .session=session, .sequence=sequence, .kind=kind, .version=1};
}

esp_err_t linkSend(const LinkPacket *p)
{
    if (configurationBusy()) return ESP_ERR_INVALID_STATE;
    return linkSendData(config.peer, p, sizeof(*p));
}

bool linkReceive(LinkPacket *p, TickType_t wait)
{
    return xQueueReceive(rxQueue, p, wait) == pdTRUE;
}

esp_err_t linkSendData(const uint8_t mac[6], const void *data, size_t size)
{
    xSemaphoreTake(radioLock, portMAX_DELAY);
    esp_err_t err = esp_now_send(mac, data, size);
    xSemaphoreGive(radioLock);
    return err;
}

esp_err_t linkSetupPeer(const uint8_t mac[6])
{
    esp_now_peer_info_t peer = {.channel=0, .ifidx=WIFI_IF_STA, .encrypt=true};
    memcpy(peer.peer_addr, mac, 6);
    memcpy(peer.lmk, setupKey, 16);
    xSemaphoreTake(radioLock, portMAX_DELAY);
    esp_err_t err = esp_now_is_peer_exist(mac) ? ESP_OK : esp_now_add_peer(&peer);
    xSemaphoreGive(radioLock);
    return err;
}

void linkForgetSetupPeer(const uint8_t mac[6])
{
    xSemaphoreTake(radioLock, portMAX_DELAY);
    if (esp_now_is_peer_exist(mac)) esp_now_del_peer(mac);
    xSemaphoreGive(radioLock);
}

esp_err_t linkSwitchConfig(const PairConfig *cfg, bool setup)
{
    if (!linkValidConfig(cfg) || (setup && !haveSetupKey)) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(radioLock, portMAX_DELAY);
    // No normal packets are sent during maintenance; re-create the Wi-Fi/ESP-NOW
    // interface so ID-derived addresses and keys change together with the channel.
    ESP_ERROR_CHECK(esp_now_unregister_recv_cb());
    ESP_ERROR_CHECK(esp_now_deinit());
    ESP_ERROR_CHECK(esp_wifi_stop());
    config = *cfg;
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, setup ? hardware : cfg->local));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_channel(setup ? 11 : cfg->channel, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk(setup ? setupKey : cfg->pmk));
    esp_now_peer_info_t peer = {.channel=0, .ifidx=WIFI_IF_STA, .encrypt=!setup};
    memcpy(peer.peer_addr, setup ? broadcast : cfg->peer, 6);
    memcpy(peer.lmk, setup ? setupKey : cfg->lmk, 16);
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    xQueueReset(rxQueue);
    xQueueReset(managementQueue);
    ESP_ERROR_CHECK(esp_now_register_recv_cb(onReceive));
    xSemaphoreGive(radioLock);
    return ESP_OK;
}
