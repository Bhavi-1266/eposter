# ePoster Architecture

## Runtime components

- `RunThis.py` loads configuration, selects API records for the hardware ID, and starts the controller.
- `helper/media_controller.py` owns the Time, Scroll, and Menu modes. One background worker fetches schedules and synchronizes the cache; a separate display worker prepares and loads media.
- `config_portal.py` provides the local administration interface.
- `helper/api_handler.py` fetches and atomically stores the poster feed.
- `helper/cache_handler.py` stores one media file per unique source URL.
- `helper/display_handler.py` prepares up to three resized still images in temporary storage, renders menu images, and holds outgoing frames during transitions.
- `helper/mpv_player.py` controls one persistent mpv process through a private Unix socket. mpv decodes videos and GIFs without Python frame arrays.
- `helper/player.lua` draws the countdown and reserved footer in the mpv window and forwards keyboard/pointer input.
- `helper/schedule.py` normalizes API timestamps to UTC and selects half-open slots (`start <= now < end`). Countdown deadlines come from the API end time.
- `helper/configuration.py` migrates `display.device_id` to `display.hardware_ID` and rejects invalid configuration reloads so the controller retains its current settings.
- `helper/json_utils.py` provides atomic JSON replacement and locked configuration updates.

## Runtime data

The following files are device-local and are intentionally excluded from Git:

- `config.json`: credentials and device settings.
- `api_data.json`: last valid poster API response.
- `event_data.json`: legacy event API response, retained when present.
- `eposter_cache/`: downloaded images and videos, keyed by URL hash.
- `.portal_secret`: persistent Flask session key.
- `.playback-status.json`: player readiness, renderer, decoder, dimensions, and heartbeat.
- `.update-status.json`: software update progress across portal restarts.
- `.venvs/`, `venv`, and `.venv-previous-*`: staged, active, and previous Python environments.

Use `config.example.json` as the source-controlled configuration schema.

## Media flow

```text
API response
    -> records for configured device
    -> unique source URLs
    -> eposter_cache/<url-sha1>.<extension>
    -> Time / Scroll / Menu display mode
    -> prepared still / cached GIF or video
    -> one persistent mpv window with countdown and footer
```

Repeated schedule slots retain their timing but share one cached media file. Menu and Scroll modes show one item per unique URL.

Failed HTTP requests, unsuccessful API responses, and payloads without a supported
schedule list preserve the saved feed. An explicit empty list is a valid schedule
update. Malformed rows are skipped without discarding other valid slots. The
existing cache routine retains files when given no records. Temporary prepared
images and transition captures are separate from the persistent cache.

## Process model

`eposter-display.service` runs the display as the desktop user. `eposter-admin.service` runs the local configuration portal. Both services restart after failures, use the system journal, and keep child processes in the service control group.

The portal is designed for a trusted LAN. It uses plain HTTP and must not be exposed directly to the public internet.

## Installation and updates

`installer.py` stages and smoke-tests a versioned Python environment before
stopping services. It refuses to switch environments if an existing service
cannot stop, preserves configuration and cache, and requires a fresh player
heartbeat after restart. Activation failure restores the previous environment
and configuration. Git changes and system packages are not rolled back.

`device_update.py` runs separately as `eposter-update.service`, pulls `origin main`
with `--ff-only`, and invokes the full installer. See [portal operations](PORTAL.md)
and [playback validation](PLAYBACK_VALIDATION.md) for operational checks.
