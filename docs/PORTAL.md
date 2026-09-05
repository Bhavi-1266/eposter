# Device portal

The management page runs independently of the Pygame display. Templates live in
templates/ and local browser assets in static/. No CDN, web font download,
frontend framework, or build command is needed.

The overview shows the display service state, available storage, memory usage,
uptime, cached media count, video player availability, and board time. These are
basic diagnostics: an active service is not proof that playback is progressing.
The feed timestamp is when saved API content changed, not its last network check.
The portal validates API URL format; it does not fetch or test the remote feed.

## Updating the board

After pulling these files into /home/rock/eposter, run:

    sudo python3 installer.py

Use the full installer for this update so requirements.txt installs Waitress.
The services-only option does not install new Python dependencies. The service
entrypoint remains config_portal.py on port 80.

Open the board's IP in a browser and sign in again. Old sessions are intentionally
invalidated because they lack the new credential/session token fields.

## Editing settings

All editable settings are grouped under Display, Content API, and Network.
Blank password/token fields retain the saved value. Clearing a saved secret
requires its separate checkbox. Saved secrets are never rendered in the page.
Existing plaintext credentials in config.json remain compatible.

Changes remain on the page after validation, network, or server errors. A timed
out save may have reached the board; check/reload before retrying. Reloading
discards unsaved edits. The portal never automatically retries a write request.
Concurrent edits from another tab or the display controller produce a conflict,
rather than overwriting the newer configuration.

Saving writes config.json atomically with its existing permissions. A held
configuration lock times out after two seconds. Missing, malformed, or unreadable
configuration produces an explicit error; default admin credentials are not
substituted. Detailed unexpected errors are logged to eposter-admin's journal.

Changes are consumed by the display on its existing playback/refresh boundaries.
The portal does not restart the display or guarantee immediate mid-video changes.

## Resource limits

- Four Waitress request threads and 32 open connections.
- 16 KB request body and header limits; 256 KB configuration read limit.
- Status is cached in memory for 30 seconds, shared across browser tabs.
- Polling pauses in hidden tabs and backs off to 120 seconds on failures.
- Cache inventory scans at most 2,048 entries; no media decoding or thumbnail generation.
- No scheduled API downloads, subprocesses, or disk writes from the portal when idle.
- NetworkManager actions are on demand, serialized, and limited to four seconds per command.

Wi-Fi power settings use the active profile UUID, not an assumed profile name.
They apply at the next reconnection. The portal does not reconnect Wi-Fi and risk
disconnecting its own management session.

## Diagnostics

    sudo journalctl -u eposter-admin.service -n 50 --no-pager
    sudo journalctl -u eposter-display.service -n 50 --no-pager

The portal provides session authentication, CSRF checks, a short sign-in attempt
limit, and local-only assets. Deployment remains a trusted LAN HTTP service.

The regression checks use temporary configuration and mocked system commands:

    python3 -m unittest discover -s tests -p test_portal.py

Waitress tuning follows https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html.
