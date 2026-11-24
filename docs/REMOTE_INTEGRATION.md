# Presenter remote integration status

This repository integrates the 24 November 2026 handoff with the ePoster player
reviewed at commit `904eb81`. The imported `firmware/` and `radxa/` trees retain
the packaged ESP-IDF firmware, UART protocol, standalone diagnostics, staff UI,
and regression checks. `SOURCE_MANIFEST.json` is the historical package manifest;
the ePoster integration files added here are intentionally outside its hash list.

## Implemented in the display lifecycle

- One reconnecting worker exclusively owns `/dev/ttyS6`, the protocol parser,
  ACK writes, and the staff `control.sock` service.
- Button/probe frames are ACKed only after bounded application-queue acceptance.
  Duplicate suppression remains in `radxa_receiver.Receiver`.
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
