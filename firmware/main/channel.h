#pragma once
#include "link.h"
void channelStart(void);
bool channelBusy(void);
uint8_t channelCurrent(void);
void channelCommand(unsigned channel, uint32_t token);
void stationMessage(const char *format, ...);
