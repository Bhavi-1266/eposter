# ePoster Architecture

## Runtime components

- `RunThis.py` owns the fullscreen display loop and the Time, Scroll, and Menu modes.
- `config_portal.py` provides the local administration interface.
- `helper/api_handler.py` fetches and atomically stores the poster feed.
- `helper/cache_handler.py` stores one media file per unique source URL.
- `helper/display_handler.py` renders images and GIFs with Pygame and delegates video to an external fullscreen player.
- `helper/json_utils.py` provides atomic JSON replacement and locked configuration updates.

## Runtime data

The following files are device-local and are intentionally excluded from Git:

- `config.json`: credentials and device settings.
- `api_data.json`: last valid poster API response.
- `event_data.json`: last valid event API response.
- `eposter_cache/`: downloaded images and videos, keyed by URL hash.
- `.portal_secret`: persistent Flask session key.

Use `config.example.json` as the source-controlled configuration schema.

## Media flow

```text
API response
    -> records for configured device
    -> unique source URLs
    -> eposter_cache/<url-sha1>.<extension>
    -> Time / Scroll / Menu display mode
    -> Pygame image or GIF / fullscreen external video player
```

Repeated schedule slots retain their timing but share one cached media file. Menu and Scroll modes show one item per unique URL.

## Process model

`eposter-display.service` runs the display as the desktop user. `eposter-admin.service` runs the local configuration portal. Both services restart after failures, use the system journal, and keep child processes in the service control group.

The portal is designed for a trusted LAN. It uses plain HTTP and must not be exposed directly to the public internet.
