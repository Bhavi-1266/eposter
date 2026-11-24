#include "link.h"
#include "channel.h"
#include "controls.h"

void runHandheld(void);
void runStation(void);

void app_main(void)
{
    // Capture a short wake press before radio startup.
    if (linkReadSetup() != ESP_OK) return;
    if (linkRole() == ROLE_HANDHELD && linkProfile() != PROFILE_CROWD) captureWakeKeys();
    if (linkStart() != ESP_OK) return;
    channelStart();
    if (linkRole() == ROLE_HANDHELD) runHandheld();
    else runStation();
}
