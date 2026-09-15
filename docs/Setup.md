# ePoster Dual-Service System

This project runs a dual-service digital signage system on DietPi and other Debian-based Linux installations with a graphical session.

## Architecture
1. **Admin Portal (`config_portal.py`)**: 
   - Runs as **Root**.
   - Binds to Port 80 (Web).
   - Provides a web portal for WiFi and device configuration.
2. **Display Controller (`RunThis.py`)**: 
   - Runs as the selected display user (sudo user or checkout owner, with **rock** as the fallback for a root-owned checkout).
   - Controls one persistent mpv window for images, GIFs, videos, menus, and API countdowns. The original cache routine runs in one background worker.
3. **Helper Modules (`helper/`)**:
   - Contains configuration, scheduling, WiFi, API, cache, and mpv playback helpers. The event-fetch helper is retained for legacy use.
4. **Service Files (`service_files/`)**:
   - Contains bash scripts and systemd service templates used by `installer.py`.



## Installation
1. Copy all project files to a directory owned by the display user.
2. Ensure `requirements.txt` and `installer.py` are in that folder.
3. Run the setup:
   ```bash
   sudo python3 installer.py
   ```

For this migration, run the full installer. See [installation and upgrade](../README.md#installation-and-upgrade) for configuration migration, environment staging, and recovery.
