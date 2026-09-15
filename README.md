# ePoster Display System

A Linux digital signage player for Radxa ROCK boards and other compatible devices. It displays cached images, GIFs, and videos in one persistent mpv window, with API-scheduled countdowns.

## Features

- 🔄 **Automatic WiFi Connection**: Supports primary and fallback WiFi networks
- 📡 **API Integration**: Fetches media records and schedules from a REST API
- 🖼️ **Image Caching**: Intelligent caching system with automatic cleanup
- 🔄 **Auto-refresh**: Periodically updates poster list from API
- 🎨 **Image Processing**: Automatic landscape conversion and rotation
- ⚙️ **Configurable**: All settings in a single `config.json` file
- 📱 **Fullscreen Display**: Optimized for portrait/landscape displays

## Requirements

- Debian 12 or a compatible Debian-based board OS with an X11 graphical session
- Python 3.10+ (Debian 12 supplies Python 3.11)
- mpv with Lua support and OpenGL video output, FFmpeg, NetworkManager
- Python packages in `requirements.txt`; installed automatically below

## Installation and upgrade

From the project checkout, owned by the display user:

```bash
sudo python3 installer.py
```

Use the **full installer for this playback migration**, including upgrades through
the webpage's Software update button. It installs mpv and fonts, stages and tests
a new Python environment, migrates configuration, and restarts both services.
There is a short service interruption during activation. `--services-only` is for
regenerating service files after dependencies have already been installed.

Set the admin credentials, API URL, and Hardware ID in `config.json` on a new
installation. The installer copies `config.example.json` only when no config
exists. It preserves existing credentials, unknown settings, and cached media.

The default display user is the invoking sudo user or project owner (with `rock`
as the root-owned deployment fallback). Override with
`sudo EPOSTER_USER=rock python3 installer.py` when necessary. Service templates
use the actual checkout path.

## Configuration

All configuration is done through `config.json`. Here's what each setting does:

### WiFi Settings

```json
"wifi": {
  "ssid1": "YourPrimaryWiFi",        // Primary WiFi network name (SSID) - first network to try connecting
  "password1": "password123",        // Password for primary WiFi network
  "ssid2": "YourBackupWiFi",         // Fallback WiFi network name (SSID) - used if primary fails
  "password2": "password456",        // Password for fallback WiFi network
  "connect_timeout": 60              // Timeout in seconds to wait for WiFi connection (default: 60)
}
```

**Notes:**
- If `ssid1` is empty, WiFi auto-connect will be skipped
- The system will try `ssid1` first, then automatically try `ssid2` if the first fails
- Leave `ssid2` empty if you only have one WiFi network

### API Settings

```json
"api": {
  "poster_token": "YOUR_TOKEN_HERE",                    // Authentication token for fetching poster images (REQUIRED)
  "poster_api_url": "https://api.example.com/posters", // URL endpoint for fetching poster list/data
  "request_timeout": 10,                                // Timeout in seconds for API requests (default: 10)
  "max_media_size_mb": 512,                              // Maximum downloaded media size
  "timezone": "Asia/Kolkata"                            // Timezone for API dates without an offset
}
```

**Notes:**
- Set `poster_token` when your API requires a key.
- The API URL must return JSON with a `screens`, `booking_slot`, or `data` list.
- Legacy `event_api_url` and `event_api_token` settings are preserved; the current
  display controller uses the poster feed for scheduling.

### Display Settings

```json
"display": {
  "hardware_ID": 1,
  "cache_refresh": 60,
  "rotation_degree": 0,
  "Auto_Scroll": 5,
  "Mode": "Time",
  "video_hwdec": "auto"
}
```

- `hardware_ID` replaces `display.device_id`, preserving its value and matching
  the existing API screen/device fields. If both exist, `hardware_ID` wins,
  including zero. The unrelated top-level `ID` is preserved.
- `rotation_degree`: 0, 90, 180, or 270 clockwise, applied to media and overlays.
- `Mode`: `Time`, `Scroll`, or `Menu`.
- Still images fill the media area above a separate footer, including 3840×2160
  UHD and portrait rotation. Different image aspect ratios stretch to fit so
  poster text is not cropped. Videos/GIFs retain their aspect ratio within that
  area. The footer reserves 56 px at 1080p and 112 px at UHD, with Paper ID on
  the left and the address on the right; it does not cover media content.
- Paper ID/address text, countdown, and menu scale with resolution. Configure
  the board's desktop output to 3840×2160 for native UHD; the player uses the
  active output size without changing HDMI modes between items. Native 4K video
  performance depends on the board's decoder, codec, and display driver.
- The player prefers mpv's `gpu-next` renderer and falls back to `gpu` on builds
  without it. `.playback-status.json` reports `video_renderer`, `display_size`,
  and the hardware decoder for checking each board's actual setup.
- `Auto_Scroll`: default dwell time in Scroll mode; the countdown still refers to
  an active API slot, never this dwell duration or the clip's duration.
- `video_hwdec`: mpv decoder preference. `auto` is the portable default; use `no`
  to diagnose software playback. On Rockchip, select `rkmpp` only after verifying
  support in the installed mpv/FFmpeg/driver stack. Logs and
  `.playback-status.json` report the decoder actually used.

For timezone-less API dates, set `api.timezone` to the same IANA timezone on every
board (for example `Asia/Kolkata`). An absent/empty value preserves the previous
system-local interpretation. Explicit ISO timestamps such as
`2026-09-15T10:00:00+05:30` retain their offset and are normalized to UTC.

## Usage

### Device Management Portal

The portal provides mobile-friendly display, API, and network settings, device
status, field-level validation, save-conflict detection, and visible connection
errors. It uses local assets and pauses status polling when the browser tab is
hidden. See [Portal operations](docs/PORTAL.md) for resource limits and diagnostics.

Use **Software update → Update software** in the portal to pull `origin main`
and run the full installer. Save or discard pending edits and enter the admin
password first. Progress survives the portal restart; reload after completion.
The device must have a clean checkout on `main` and noninteractive access to its
Git remote. Updates use `git pull --ff-only origin main` and preserve ignored
configuration and runtime files.

To enable this button on an older device, pull this release and run once:

```bash
cd /home/rock/eposter
sudo python3 installer.py
```

Update jobs run independently as `eposter-update.service`. For diagnostics:

```bash
sudo journalctl -u eposter-update.service --no-pager
```

If installation fails after pulling, code may already be updated. Resolve the
reported issue and retry the full installer. The installer restores the previous Python environment and configuration if activation fails; Git source changes and OS packages are not automatically rolled back.

### Local Test API

The development server reads its JSON source on every request, so timing and media changes do not require a restart. It can also serve local images and videos.

```bash
mkdir -p local_test/media
cp tools/local_api_data.example.json local_test/api_data.json
cp /path/to/poster.png local_test/media/poster.png
cp /path/to/video.mov local_test/media/video.mov
python3 tools/local_api.py
```

Point the display configuration at:

```json
"poster_api_url": "http://127.0.0.1:8080/api/posters"
```

Edit `local_test/api_data.json` to change records or `duration_seconds`. Saving the file resets the generated schedule cycle. The entire `local_test/` directory is ignored by Git. To test from another device, start the server with `--host 0.0.0.0` and use the server computer's LAN IP in both the display configuration and generated media URLs.

### Starting the Display

Run the display controller:

```bash
python3 RunThis.py
```

Or with full path:

```bash
python3 /path/to/eposter/RunThis.py
```

The controller will:
1. Load configuration from `config.json`
2. Connect to WiFi (if configured)
3. Fetch posters from API
4. Display them in a fullscreen slideshow

### Playback and countdown

Images, GIFs, videos, the menu, and the countdown use one persistent mpv window.
The existing cache/download algorithm is unchanged and runs in one background
worker. At most three screen-sized still images are prepared in temporary
storage; animations and videos are decoded by mpv, never expanded into Python
frame arrays. Temporary presentation files are separate from `eposter_cache`.

The countdown is always `max(0, API end_date_time - current time)`:

- A late start or restart shows the actual remaining slot time.
- A short video/GIF loops until the API deadline; a long clip stops at it.
- API refreshes and media loops do not reset the countdown.
- Slots use `start <= now < end`; an adjacent slot owns the exact boundary.
- Missing scheduled media shows a waiting screen with the same API deadline.
- Menu/Scroll show a countdown only when the selected media has an active API
  slot. Manual previews without an active slot have no countdown.
- The menu list and unscheduled screensaver have no countdown.

During a media switch, a captured frame covers loading until the next first
frame is ready. The live countdown and footer remain uncovered. The player keeps
its window open and does not request resolution/refresh-rate changes. If the
video output cannot capture its window, mpv's keep-open behavior is the fallback;
fully gapless behavior still requires validation on the board's video driver.

Press `q` to exit. In Menu, click or press Enter to preview an item; click or press
Escape to return. Use arrows, wheel, Page Up/Down, or drag to browse. The Start
Schedule button switches to Time mode.

### Installer recovery

The first migration saves `config.json.before-player-update` with restricted
permissions. A versioned environment is installed under `.venvs/`, tested as the
display user with real headless mpv, then activated through `venv`. The previous
environment is retained; older installer-owned environments are pruned after a
successful update. Activation failures restore the old environment and config.
The installer waits for a new player heartbeat, not just systemd's active state.
The existing webpage update job continues to invoke the full installer.

`sudo python3 installer.py --services-only` validates the existing environment,
regenerates the service files, and restarts services without installing packages.
The service still targets an X11 session on `:0`; a Wayland-only deployment needs
an appropriate service/session configuration. Hardware codec support and HDMI
behavior must be checked per board family.

### Validation

```bash
python3 -m unittest discover -s tests -v
python3 tools/playback_smoke.py --integration
# Optional virtual-display rendering/transition capture (requires Xvfb):
python3 tools/playback_smoke.py --visual
```

The smoke tests use temporary sample media and do not modify the device cache or
API feed. See [playback validation](docs/PLAYBACK_VALIDATION.md) for checks and
physical-device acceptance criteria.

## File Structure

```
eposter/
├── RunThis.py               # Main display controller
├── config_portal.py         # Captive portal and device configuration
├── installer.py             # System setup and service installer
├── config.example.json      # Source-controlled configuration schema
├── config.json              # Device-local configuration (ignored by Git)
├── ScreenSaver.png/.gif     # Screensaver asset; GIF animates when present
├── helper/                  # Runtime helper modules
│   ├── api_handler.py       # API calls and data handling
│   ├── cache_handler.py     # Image caching and processing
│   ├── display_handler.py   # Persistent mpv display and image preparation
│   ├── media_controller.py # Time, Scroll, Menu, and background refresh
│   ├── mpv_player.py       # Persistent player and JSON IPC
│   ├── player.lua          # Countdown, footer, and input
│   ├── configuration.py    # Validated loading and identifier migration
│   ├── schedule.py         # API timestamps and slot selection
│   ├── fetch_event_data.py # Legacy event-fetch helper
│   └── wifi_connect.py      # WiFi connection module
├── service_files/           # Bash scripts and systemd service templates
│   ├── eposter-admin.service.template
│   ├── eposter-display.service.template
│   └── wifi_powersave.sh    # WiFi power-save helper script
├── docs/                    # Setup and operations notes
├── eposter_cache/           # Cached poster images (auto-created, ignored)
├── api_data.json            # Saved API response (auto-created, ignored)
├── event_data.json          # Legacy event information, when present
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## How It Works

1. **WiFi Connection**: `helper/wifi_connect.py` attempts to connect to configured WiFi networks
2. **API Fetching**: `helper/api_handler.py` fetches poster data from the API
3. **Media Caching**: `helper/cache_handler.py` downloads and processes images/videos:
   - Media files are deduplicated by their source URL (`eposter_file`/`file`)
   - One URL is stored as a single cache file and shared across duplicate records
   - Old/unused media files are automatically deleted
   - Repeated schedule rows are reduced to one download/check per unique URL
4. **Display**: `helper/media_controller.py` selects media for Time, Scroll, or Menu;
   `helper/display_handler.py` prepares it for one persistent mpv window.
   - Menu mode displays a generated video tile; tapping it starts playback.
   - GIFs and videos loop in mpv while the countdown follows the API end time.
5. **Auto-refresh**: One worker periodically checks for schedules and media.
   Failed requests and invalid/error API responses preserve the saved feed.
   Unreadable configuration reloads retain the current settings.

## Troubleshooting

### WiFi Not Connecting

- Check that `nmcli` is installed: `which nmcli`
- Verify WiFi credentials in `config.json`
- Check WiFi is enabled: `nmcli radio wifi on`
- View WiFi status: `nmcli device status`

### No Posters Displaying

- Verify `poster_token` is correct in `config.json`
- Check API URL is accessible: `curl "YOUR_API_URL?key=YOUR_TOKEN"`
- Check console output for error messages
- Verify images are being cached: `ls eposter_cache/`

### Images Not Rotating

- Check `rotation_degree` in `config.json`
- Ensure images are being processed (check console logs)
- Check the playback log; display rotation does not require clearing the media cache.

### Permission Errors

- Ensure script has write permissions in the directory
- Check file ownership: `ls -la`
- May need to run with appropriate user permissions

### Display Issues

- Verify mpv is installed: `mpv --version` and run `python3 tools/playback_smoke.py`
- Check display is accessible: `echo $DISPLAY`
- For headless systems, may need X11 forwarding or virtual display

## Runtime configuration

The controller reads `config.json` directly and reloads settings every second.
The installer accepts `EPOSTER_USER` to choose the display account and configures
the service's X11 session variables. Media, API, and Wi-Fi settings belong in
`config.json`; the controller does not read environment-variable overrides for them.

## API Response Format

The poster API should return JSON in one of these formats:

**Format 1 (Recommended):**
```json
{
  "status": true,
  "message": "ePoster Fetched Successfully",
  "data": [
    {
      "PosterId": 6,
      "screen_number": 1,
      "paper_id": "P-006",
      "poster_title": "My Poster",
      "eposter_file": "https://example.com/image.jpg",
      "start_date_time": "2026-09-16T10:00:00+05:30",
      "end_date_time": "2026-09-16T10:05:00+05:30"
    }
  ]
}
```

**Format 2 (Legacy):**
```json
{
  "data": [
    {
      "id": 6,
      "screen_number": 1,
      "file": "https://example.com/image.jpg",
      "start_date_time": "2026-09-16T10:00:00+05:30",
      "end_date_time": "2026-09-16T10:05:00+05:30"
    }
  ]
}
```

Records need valid start/end timestamps and a matching hardware/screen ID.
`screens` and `booking_slot` may instead contain objects with a screen ID and a
`records` list. Supported ID fields are `hardware_ID`, `screen_number`,
`screen_id`, `device_id`, `screen`, and `display_id`. An explicit empty schedule
list clears scheduled playback; failed or structurally invalid API responses
leave the previous saved schedule available.

## Support

For issues or questions, please check the console output for error messages and verify your `config.json` settings.
