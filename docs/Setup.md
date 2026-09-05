# ePoster Dual-Service System

This project runs a dual-service digital signage system on DietPi and other Debian-based Linux installations with a graphical session.

## Architecture
1. **Admin Portal (`config_portal.py`)**: 
   - Runs as **Root**.
   - Binds to Port 80 (Web).
   - Provides a web portal for WiFi and device configuration.
2. **Display Controller (`RunThis.py`)**: 
   - Runs as user **rock**.
   - Manages the Pygame GUI, API syncing, and content rotation.
3. **Helper Modules (`helper/`)**:
   - Contains WiFi, API, cache, display, and event-fetch helpers used by the root entrypoints.
4. **Service Files (`service_files/`)**:
   - Contains bash scripts and systemd service templates used by `installer.py`.



## Installation
1. Copy all project files to a directory owned by the display user.
2. Ensure `requirements.txt` and `installer.py` are in that folder.
3. Run the setup:
   ```bash
   sudo python3 installer.py
   ```
