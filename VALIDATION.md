# Validation — 23 November 2026

## Button LED feedback and deep sleep — 23 November 2026

Latest shared firmware supersedes the earlier USB-awake behavior for the production matrix profile. All nine debounced button presses, including AIM/S9, get an80ms active-LOW LED pulse; held AIM does not continuously light the LED. Special setup/calibration/sensitivity patterns retain priority. S9 still has no presenter action, but participates in startup capture, LED feedback and idle activity. Existing button actions receive only the original eight action bits. LED output is refreshed after setup mode to avoid stale cached polarity.

The matrix sender enters true ESP deep sleep after33 idle seconds, including with USB data connected. Held keys, calibration, configuration, queued button events and active transmissions/bursts prevent idle sleep. Any matrix key is configured to wake it. The receiver stays awake; one/two-button fixtures remain awake as before. MPU sleep on AIM release and before ESP deep sleep is now verified by reading PWR_MGMT_1 bit6; wake is also read back. One private setMpuSleep operation owns this write/readback/state update, with no new task, queue or mutex. A failed final MPU check is warned; ESP still sleeps, so never infer MPU current from the warning case. Wi-Fi is explicitly stopped before ESP deep sleep, with LED HIGH/OFF held. Boot logs distinguish a deep-sleep wake. Existing saved calibration and pairing formats are unchanged.

Both ESP32 and C3 builds passed using ESP-IDF5.5.5. User changed the idle timeout to33seconds. The update was app-only flashed to identified C3 sender COM11 (factory MAC24:58:7c:84:00:d8), with flash hash verified. Normal remote-001/channel11 and saved calibration ready at322ms were confirmed. MPU sleep register readback0x40 passed. First ESP deep-sleep entry was logged at33331ms uptime and COM11 disappeared. User pressed S9 and confirmed wake plus LED blink; COM11 reappeared. A second sleep entry was logged at33372ms of the next boot. Early wake-reason logs were missed during USB re-enumeration, so do not claim that line was captured. Current consumption and the remaining eight wake keys were not measured/tested in this run.

Current visible monitor PID13888 uses tmp/input-power-20261123/log.radxa_remote.20261123213839.txt. It resets once on initial start, then reconnects without resets after sleep. The earlier monitor PIDs11260/2788 were closed. Evidence is result-33.json, build-33-esp32/c3.log and flash-33-COM11.log in that folder. Build caches remain outside the source tree in tmp/led-sleep-20261123. Current source timeout is33seconds in firmware/main/board.h and README. No Radxa work or deployment was performed.

User reports C10-C12 DNP and diode footprint/part marking corrected; no revised schematic supplied to verify. User observed the previous firmware LED stayed OFF at idle and lit on ordinary buttons, except AIM and S9. Keep the currently connected 3V3 ->2.2k ->blue LED ->GPIO21 arrangement. A100k pull-up to3V3 carries negligible current at HIGH/OFF and about33uA only at LOW/ON; active-HIGH with pull-down can also have low standby current. C3 digital pin hold supports deep sleep via gpio_hold_en plus gpio_deep_sleep_hold_en; it is not restricted to light sleep.

## LED bench connection — 23 November 2026

The user subsequently connected a blue LED as 3V3 -> 2.2k -> LED -> GPIO21 and authorized checking the sender. COM11 was identified as C3 revision 0.4, factory MAC 24:58:7c:84:00:d8. Application-only flash passed and preserved pair/calibration partitions. The visible monitor confirmed remote-001/channel11, matrix profile, MPU6500 at0x69 and saved AIM calibration ready at322ms, sensitivity2/3. Monitor PID11260, evidence tmp/led-sleep-20261123/flash-COM11.log and log.radxa_remote.20261123211849.txt. User LED observation and a power-without-USB-data arrangement are pending; final firmware intentionally prevents idle sleep while native USB data is connected. No physical sleep/wake success claimed and no Radxa work performed.

## LED sleep retention — 23 November 2026

The shared controls code now drives the active-LOW LED HIGH/OFF and enables its per-pin hold before deep sleep. At wake it prepares the HIGH output before releasing the hold. Fresh ESP-IDF 5.5.5 builds passed for ESP32 and ESP32-C3; the initialization/sleep ordering was also inspected. Build logs and the small source diff are outside this source folder at `C:/projects-esp/radxa_control/tmp/led-sleep-20261123`.

No firmware was flashed and no physical sleep/wake test was performed for this change. GPIO21 ROM UART activity during cold boot is separate from the deep-sleep hold behavior. Add the recommended 100 kΩ GPIO21-to-3V3 pull-up to establish LED OFF while high impedance; confirm the assembled behavior on hardware.

## Verified

- Shared firmware built for ESP32-WROOM-32 and ESP32-C3 with ESP-IDF5.5.5.
- Connected C3 matrix sender and UART receiver flashed and tested with ROCK 5C.
- All nine matrix positions detected. Saved MPU calibration survives restart; AIM ready was logged at322ms after boot.
- User confirmed S5 play/pause and S7 hold-to-AIM after the final configuration tests.
- Coordinated channel11→6→3→11 and ID/channel changes confirmed on both ESPs. Those four configuration transactions took0.792–0.849seconds; this is not input latency.
- Both ESPs retained changed ID/channel after restart. With the sender unavailable, the receiver returned ROLLED_BACK after15.075seconds; the restarted sender rejoined the original pair.
- Physical S7+S9 setup entry, spare discovery, identify request, save to a temporary ID/channel, and restoration to remote-001/channel11 passed. Roles/profiles were preserved.
- UART pseudo-terminal integration, long configuration responses alongside button ACKs, GTK UI and actual Read pair settings action passed. The UI was visually inspected.
- Production C simulations passed lost-proof/final-ACK/commit-message cases, restart recovery, spare identity checks, saved spare settings and lost-exit recovery. Simulations mock radio/NVS/crypto and do not replace hardware testing.

## Still to test

Physical WROOM pairs, five-person crowd testing, an independent staff Radxa controlling other stations, PCB battery life and wake behavior. Current results are not conference-scale qualification.

## Repository cleanup

The active source and current regression checks are retained. Old compiled image packages, build/cache output, example JSON files and the replaced channel-only staff UI were removed. Fresh-checkout setup generation no longer depends on an example file; normal `idf.py build flash monitor` remains the programming flow. Private key/setup files remain local and ignored by Git.

After cleanup, all eight configuration/provisioning checks passed. Generated pair-partition bytes matched the previous build exactly; actual local key, setup JSON and IDE files were unchanged. The staff launcher points to the current UI. No hardware reflash or Radxa deployment was needed for this folder cleanup.

Detailed bench logs and pre-cleanup history are retained outside this source folder in the local workspace. No credentials or private flash backups belong in Git.
