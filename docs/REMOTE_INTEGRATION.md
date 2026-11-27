# Presenter remote integration status

This repository integrates the 24 November 2026 handoff with the ePoster player
reviewed at commit `904eb81`. The imported `firmware/` and `radxa/` trees retain
the legacy ESP-IDF firmware, standalone diagnostics, staff UI, and regression
checks. `SOURCE_MANIFEST.json` describes the original handoff snapshot.

## Set up UART6 on the ROCK 5C

Use the physical pin numbers **19 TX → ESP RX**, **21 RX ← ESP TX**, and
**20 GND → ESP GND**. The link uses 3.3 V logic and 115200 8N1.

The full installer runs `tools/setup_uart6.sh`. To run that step by itself:

```sh
sudo bash tools/setup_uart6.sh
```

The script detects the ROCK 5C, backs up the boot configuration under
`/var/backups/eposter/uart6/`, and enables and verifies `rk3588-uart6-m1.dtbo`.
It restores `extlinux.conf` if the overlay fails verification. The log is at
`/var/log/eposter/uart6-setup.log`. Reboot once after enabling UART6-M1 and
check that `/dev/ttyS6` exists. Pass `--reboot` to the standalone script to
reboot automatically when activation needs it.

After reboot, confirm `presenter_remote.enabled` is `true` and the port is
`/dev/ttyS6` in `config.json`. The display journal should show that it opened the
UART. Press OK during an active video in Time mode to test pause and resume.
Accepted button presses appear as `Remote button pressed: OK` in the
`RunThis.py` terminal or the display service journal, even when the display
mode has no action for that button.

For a laptop test, start the display in your desktop session:

```sh
EPOSTER_TOUCHPAD_AIM=1 ./venv/bin/python RunThis.py
```

Focus the player and hold **A** while moving the touchpad. Each press starts
the red AIM dot at the center of the playback area. Movement uses the same
rotation, speed, and fade behavior as the remote AIM pointer. Test in
Time mode, including on the screensaver. **Space** simulates OK during an
active scheduled video. The environment flag also works with the local
time-shifted preview launcher.

## JSON v1 receiver settings

Run the command as the display user on the station while the display service
owns the UART:

```sh
python3 radxa/remote set-config remote-001 --device-id remote-012 --channel 6
```

The first argument is the current ID. Pass either setting or both. The command
uses the display's existing Unix control socket. Success requires the receiver
to return a matching `config_result` with `status: "ok"` and the confirmed
values after both ESPs apply the change. If the result times out, verify which
ID and channel the pair is using before repeating the command.

The JSON settings command requires a receiver with JSON v1 firmware. The
firmware bundled in the original handoff continues to use `EV`, `CHANNEL`,
and `RCFG` on UART. Use `radxa/configure.py` for that firmware.

## Implemented in the display lifecycle

- One reconnecting worker exclusively owns `/dev/ttyS6`, the protocol parser,
  ACK writes, and the staff `control.sock` service.
- JSON input lines are ACKed after acceptance, including streamed AIM deltas.
  A repeated input ID gets another ACK with no second action. The JSON reader
  remembers the most recent 4096 button IDs and 4096 motion/empty-report IDs in
  memory across UART reconnects. The legacy receiver ACKs button/probe frames.
- Motion is coalesced, bounded and expired independently of the ordered button
  queue. It drives an mpv ASS cursor inside the application window; no desktop
  pointer injection is used.
- The controller thread consumes remote events. OK toggles play/pause only when
  the selected scheduled path is the video currently visible in mpv.
- A media transition clears pause state, so the API deadline always changes the
  item on time even if the outgoing video was paused.
- Display rotation is applied to AIM deltas and coordinates, and the pointer is
  bounded above the reserved footer.
- Back/Home can return from staff-selected Menu/preview state to the active Time
  schedule. The presenter remote cannot enter or navigate the existing library.
- The installer adds the display user to `dialout` when that group exists.

## Deliberately not claimed

The current API/player has no author-scoped PDF/URL viewer, zoom/pan model, or
session-scoped link targets. Directional presenter actions and remote selection
from the screen-wide poster library are therefore disabled: enabling them could
expose another author's content. S9 remains reserved and is not transmitted by
the packaged firmware. Those features require an explicit application/data-model
design and physical landscape/portrait acceptance testing.

Run the standalone `radxa/remote` video/listener only for diagnostics, never at
the same time as the integrated display service, because only one process may own
the UART.
