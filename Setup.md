# ePoster Dual-Service System

This project runs a dual-service digital signage system on RakshaOS.

## Architecture
1. **Admin Portal (`config_portal.py`)**: 
   - Runs as **Root**.
   - Binds to Port 80 (Web) and Port 53 (DNS).
   - Provides a Captive Portal for WiFi and device configuration.
2. **Display Controller (`RunThis.py`)**: 
   - Runs as user **rock**.
   - Manages the Pygame GUI, API syncing, and content rotation.



## Installation
1. Copy all project files to `/home/rock/Desktop/eposter_latest/eposter-main`.
2. Ensure `requirements.txt` and `setup_eposter.py` are in that folder.
3. Run the setup:
   ```bash
   sudo python3 setup_eposter.py