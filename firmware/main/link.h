#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

enum { ROLE_HANDHELD = 1, ROLE_STATION = 2 };
enum { EVENT_KEY = 1, EVENT_MOVE, EVENT_TEST, EVENT_ACK, CH_OFFER, CH_VERIFY, CH_PROOF, CH_WHERE, CH_HERE, CH_DONE };
/* Values are stored in the pair configuration. Append new profiles at the end. */
enum { PROFILE_TWO_BUTTON, PROFILE_MATRIX, PROFILE_CROWD, PROFILE_ONE_BUTTON };
typedef struct {
    uint8_t magic[4], role, channel, local[6], peer[6], pmk[16], lmk[16], profile, generation[4];
    char id[65];
} PairConfig;
_Static_assert(sizeof(PairConfig) == 120, "pair config layout");
typedef struct {
    uint32_t magic, session, sequence;
    union {
        struct { int16_t x, y; uint16_t batteryMv; };
        char text[6];
    };
    uint8_t kind, version;
} LinkPacket;

esp_err_t linkReadSetup(void);
esp_err_t linkStart(void);
uint8_t linkRole(void);
uint8_t linkProfile(void);
uint8_t linkDefaultChannel(void);
const char *linkId(void);
uint32_t linkConfigTag(void);
void linkTune(uint8_t ch);
bool linkManagement(LinkPacket *p);
esp_err_t linkSend(const LinkPacket *p);
bool linkReceive(LinkPacket *p, TickType_t wait);
LinkPacket linkPacket(uint8_t kind, uint32_t session, uint32_t sequence);
bool linkValidConfig(const PairConfig *cfg);
void linkGetConfig(PairConfig *cfg);
esp_err_t linkSwitchConfig(const PairConfig *cfg, bool setup);
esp_err_t linkSetupPeer(const uint8_t mac[6]);
void linkForgetSetupPeer(const uint8_t mac[6]);
esp_err_t linkSendData(const uint8_t mac[6], const void *data, size_t size);
const uint8_t *linkSetupKey(void);
bool linkHasSetupKey(void);
void linkHardwareAddress(uint8_t mac[6]);
