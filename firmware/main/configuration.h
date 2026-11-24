#pragma once
#include "link.h"

esp_err_t configurationLoad(PairConfig *cfg, uint32_t factoryTag);
void configurationInit(void);
bool configurationReceive(const uint8_t mac[6], const void *data, int size);
// Called only by the channel task, which owns radio configuration changes.
bool configurationTick(int64_t nowMs);
bool configurationBusy(void);
bool configurationNeedsChannelSync(void);
void configurationCommand(uint32_t token, const char *operation, const char *hex);
void configurationEnterSpare(void);
bool configurationLed(int64_t nowUs);
