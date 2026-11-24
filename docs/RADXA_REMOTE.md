# Radxa presenter remote

- `firmware/`: one ESP-IDF project for ESP32-WROOM-32 and ESP32-C3, sender or receiver.
- `radxa/`: UART receiver, presenter video tool and staff configuration UI.
- `firmware/schematic/`: Rev C PCB reference drawings; [assembly and reserve-footprint notes](firmware/schematic/PCB_NOTES.md).
- The `tests/` folders contain current regression checks, not alternate firmware.

## Program an ESP

Open `firmware/` in the ESP-IDF terminal. ESP-IDF 5.5.5 was used for validation.

```sh
idf.py set-target esp32c3
```

Use `esp32` instead for WROOM. On a fresh checkout, restore the fleet's existing `data/encryption_key.txt`, then run `python generate_key.py`. It creates a starter `data/setup.json` without replacing existing settings or keys. For a completely new fleet, it can generate the key too. All paired boards and the staff bridge must use the same fleet key.

Edit `data/setup.json`:

```json
{"device_id": "remote-001", "channel": 11, "role": "sender"}
```

Then build, flash and monitor:

```sh
idf.py build flash monitor -p COM11
```

For the receiver, change only `role` to `receiver` and use its COM port. Keep ID, channel and fleet key matched. Exit the monitor with **Ctrl+]**. The ESP-IDF build includes the private pair settings automatically; no separate flashing command is needed.

The default profile is the 3×3 keypad. For the WROOM one-button crowd fixtures, add `"profile": "presenter-one-button"` and wire OK between GPIO16 and 3.3 V. The existing two-button fixture uses `"profile": "presenter-two-button"`, OK on GPIO6 and AIM on GPIO7 for C3, both switched to 3.3 V. The direct-button fixtures stay awake for testing.

## Controls and wiring

| Key | Function | Key | Function | Key | Function |
|---|---|---|---|---|---|
| S1 | Back | S2 | Up | S3 | Home |
| S4 | Left | S5 | OK / play-pause | S6 | Right |
| S7 | Hold to AIM | S8 | Down | S9 | Mode; alone reserved |

- Hold AIM, tap Home, release both and leave still: staff gyro calibration, saved in flash.
- Hold AIM, tap OK: sensitivity change. Release both before pointing.
- Hold **both S7 + S9 for 3 seconds**: nearby configuration mode; LED blinks.

Every keypad press, including AIM and S9, gives a short LED pulse. S9 remains reserved for a presenter action. After 33 idle seconds the matrix sender enters deep sleep, including when USB is connected; any keypad button wakes it. The MPU sleeps when AIM is released and is checked again before ESP sleep. The receiver stays awake. USB monitoring disconnects during deep sleep; press a keypad button to reconnect, or use BOOT/RESET for flashing recovery.

C3 keypad rows: GPIO0/1/3; columns: GPIO6/7/10. MPU: SDA5, SCL20, address 0x68 or 0x69. Use the [schematic](firmware/schematic/02-controller-inputs.svg) for diodes, pull-ups and power; target-specific pins are centralized in `firmware/main/board.h`.

| ROCK 5C physical header | C3 receiver | WROOM receiver |
|---|---|---|
| 19 — UART6 TX | GPIO20 RX | GPIO16 RX |
| 21 — UART6 RX | GPIO21 TX | GPIO17 TX |
| 20 — GND | GND | GND |

Enable UART6-M1 on the ROCK 5C. UART is `/dev/ttyS6`, 115200 8N1, 3.3 V logic. Use one power source for the receiver board and share ground.

## Run on Radxa

Copy the contents of `radxa/` to `~/Prashant/remote`. From the desktop terminal:

```sh
cd ~/Prashant/remote
python3 remote video
```

This starts the receiver and moving video together. Use `python3 remote video --file /path/to/poster.mp4` for a submitted video. Keep its window active for AIM. `python3 remote start` is a console-only listener; run only one UART owner. Video/UI dependencies are Python3, GTK3, GStreamer and the GTK video sink.

## Staff configuration

Leave the receiver/video running and open the separate staff UI:

```sh
python3 configure.py
```

**LAN:** enter `rock@IP`, select a registered ID, or use `local`. Read both ESPs, edit ID/channel and Send. The awake sender and receiver change together; roles/profiles remain locked. The JSON preview is read-only. `python3 remote staff` opens this same UI.

**Spare:** hold both S7+S9 for 3 seconds on the spare. Choose Spare mode, start the staff receiver bridge, scan, select and Identify its LED. Enter the replacement ID/channel and Send. Switch off the old remote before using the replacement. End setup to restore the staff receiver's normal pair; setup also expires after 3 minutes. The spare retains its own gyro calibration.

Put the approved fleet key at `radxa/private/encryption_key.txt` on the staff machine, with directory permissions 700 and file 600. Keep nearby setup to one staff bridge at a time. For ID-based LAN selection, create local `stations.json`, for example `{"remote-001":"local","remote-002":"rock@192.168.1.20"}`. Establish trusted SSH key login from the staff Radxa to each other station first. Only the selected station receives the request.

Success means saved settings were confirmed. **Not confirmed** requires readback before retrying. A failed new-link verification rolls the receiver back; the handheld searches its saved old/new settings to recover. Runtime changes live in NVS; they do not edit the laptop's `setup.json`. Reflashing identical programming defaults preserves them; changed defaults reset the override. USB programming with BOOT/RESET remains the recovery path.

## Repository checks

Keys, local setup/station files, IDE settings, builds and logs are excluded from Git. Build firmware locally; compiled snapshots are not kept in the repository.

Run `python -B radxa/tests/configuration.py` for configuration/provisioning tests. Linux checks are `firmware/tests/configuration_sim.py`, `firmware/tests/channel_sim.py`, `radxa/tests/station_pty.py` and the desktop `radxa/tests/configure_ui.py`; C simulations need a C compiler and headers. See [validation](VALIDATION.md) for hardware results and remaining crowd/PCB tests.
