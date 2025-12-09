# ePoster Display System

A Raspberry Pi-based digital poster display system that automatically fetches and displays poster images from an API in a fullscreen slideshow.

## Features

- 🔄 **Automatic WiFi Connection**: Supports primary and fallback WiFi networks
- 📡 **API Integration**: Fetches posters and event data from REST APIs
- 🖼️ **Image Caching**: Intelligent caching system with automatic cleanup
- 🔄 **Auto-refresh**: Periodically updates poster list from API
- 🎨 **Image Processing**: Automatic landscape conversion and rotation
- ⚙️ **Configurable**: All settings in a single `config.json` file
- 📱 **Fullscreen Display**: Optimized for portrait/landscape displays

## Requirements

- Raspberry Pi (or Linux system)
- Python 3.6+
- NetworkManager (`nmcli`) for WiFi management
- Required Python packages:
  ```bash
  pip3 install requests pillow pygame
  ```

## Installation

1. Clone or copy this repository to your Raspberry Pi:
   ```bash
   cd /home/pi/eposter  # or your preferred location
   ```

2. Install dependencies:
   ```bash
   pip3 install requests pillow pygame
   ```

3. Configure your settings in `config.json` (see Configuration section below)

4. Make launcher executable:
   ```bash
   chmod +x launcher.sh
   ```

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
  "event_api_url": "https://api.example.com/events",    // URL endpoint for fetching event information/data
  "event_api_token": "",                                 // Optional authentication token for event API (leave empty if not needed)
  "request_timeout": 10                                  // Timeout in seconds for API requests (default: 10)
}
```

**Notes:**
- `poster_token` is **REQUIRED** - the system will not start without it
- `event_api_token` is optional - leave as empty string if not needed
- Both API URLs should return JSON responses

### Display Settings

```json
"display": {
  "cache_refresh": 60,        // How often to refresh poster cache from API (in seconds, default: 60)
  "display_time": 5,           // How long to display each poster image (in seconds, default: 5)
  "rotation_degree": 0         // Rotation angle for images in degrees:
                               //   0 = no rotation
                               //   -90 = rotate left (counter-clockwise)
                               //   90 = rotate right (clockwise)
                               //   default: 0
}
```

**Notes:**
- `cache_refresh`: Lower values = more frequent updates but more API calls
- `display_time`: How long each poster is shown before moving to the next
- `rotation_degree`: Adjust if your display is mounted in a different orientation

## Usage

### Starting the Display

Simply run the launcher script:

```bash
./launcher.sh
```

Or with full path:

```bash
/path/to/eposter/launcher.sh
```

The script will:
1. Load configuration from `config.json`
2. Connect to WiFi (if configured)
3. Fetch posters from API
4. Display them in a fullscreen slideshow

### Stopping the Display

Press `ESC` or `Q` to exit the display.

### Running as a Service (systemd)

To run automatically on boot, you can create a systemd service. See `eposter-launch.service_CREATOR` for an example.

## File Structure

```
eposter/
├── launcher.sh              # Main launcher script (reads config.json)
├── config.json              # Configuration file (edit this!)
├── show_eposters.py         # Main Python script
├── wifi_connect.py          # WiFi connection module
├── api_handler.py           # API calls and data handling
├── cache_handler.py         # Image caching and processing
├── display_handler.py       # Pygame display management
├── fetch_event_data.py      # Event data fetching
├── eposter_cache/           # Cached poster images (auto-created)
├── api_data.json            # Saved API response (auto-created)
├── event_data.json          # Event information (auto-created)
└── README.md                # This file
```

## How It Works

1. **WiFi Connection**: `wifi_connect.py` attempts to connect to configured WiFi networks
2. **API Fetching**: `api_handler.py` fetches poster data from the API
3. **Image Caching**: `cache_handler.py` downloads and processes images:
   - Images are named by their poster ID (e.g., `6.png`, `7.png`)
   - Images are converted to landscape orientation
   - Old/unused images are automatically deleted
4. **Display**: `display_handler.py` shows images in a fullscreen slideshow
5. **Auto-refresh**: The system periodically checks for new posters

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
- Try clearing cache: `rm -rf eposter_cache/*`

### Permission Errors

- Ensure script has write permissions in the directory
- Check file ownership: `ls -la`
- May need to run with appropriate user permissions

### Display Issues

- Verify pygame is installed: `python3 -c "import pygame"`
- Check display is accessible: `echo $DISPLAY`
- For headless systems, may need X11 forwarding or virtual display

## Environment Variables

The launcher script exports these environment variables from `config.json`:

- `WIFI_SSID`, `WIFI_PSK` - Primary WiFi
- `WIFI_SSID_2`, `WIFI_PSK_2` - Fallback WiFi
- `WIFI_CONNECT_TIMEOUT` - WiFi timeout
- `POSTER_TOKEN` - Poster API token
- `API_BASE` - Poster API URL
- `EVENT_API_URL` - Event API URL
- `EVENT_API_TOKEN` - Event API token
- `REQUEST_TIMEOUT` - API request timeout
- `CACHE_REFRESH` - Cache refresh interval
- `DISPLAY_TIME` - Image display duration
- `ROTATION_DEGREE` - Image rotation angle

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
      "poster_title": "My Poster",
      "eposter_file": "https://example.com/image.jpg",
      ...
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
      "file": "https://example.com/image.jpg",
      ...
    }
  ]
}
```

## License

[Add your license here]

## Support

For issues or questions, please check the console output for error messages and verify your `config.json` settings.
