# Playback migration validation

Initially validated locally on 2026-09-15 and rechecked on 2026-09-16 with
mpv 0.40.0, FFmpeg 7.1.x, and private
960×540, 1920×1080, and 3840×2160 Xvfb displays using software OpenGL rendering.
The final 1080p/UHD checks used `gpu-next`. No live board, real API,
production media cache, or system service installation was used for these tests.

## Results

| Check | Result |
| --- | --- |
| Python regression suite | 75 tests passed on 2026-09-16 |
| Configuration migration | Legacy `device_id`, zero values, new-key precedence, permissions, idempotence, and unrelated settings preserved |
| Portal | Hardware ID rendering/save/status, legacy form compatibility, authentication, CSRF, stale revisions, storage failures, and update launch covered |
| Schedule/timer | API end time, late startup/restart, unchanged refresh, changed deadlines, timezone offsets, adjacent boundaries, missing media, Menu and Scroll covered |
| Existing cache + actual HTTP API + scheduler + real mpv | Passed using temporary files; image/video/GIF slots played in one process; second refresh did not redownload media |
| Real mpv controls | PNG, portrait image, animated GIF, MP4, loop events, countdown continuity, four rotation settings, corrupt-file recovery, and disconnect detection passed |
| Rendered transitions, including video loops | Latest footer layout run at 1080p: 511 frames captured at 60 fps; zero black center pixels in the colored test sequence; player PID and X11 window ID stayed constant |
| Rendered overlays/menu | Screenshots inspected for all four rotations; menu thumbnail/text layout and Enter input checked |
| UHD image layout | Native 3840×2160 output and four rotations verified; undersized/mismatched images fill exposed screen edges; edge content retained; 4K footer cutouts and menu hit areas covered |
| Full UHD transition sequence | Latest footer layout run: 279 frames sampled at 15 fps with zero black center pixels; both stills, GIF and video observed; same process/window throughout |
| Reserved footer | Actual video bounds, visible bottom edge of the poster, opaque footer, and left Paper ID/right address verified at 1080p and UHD in all four rotations |
| Installer | Dependency-failure sequencing, environment activation/restoration, config backup, cache preservation, templated user/path, heartbeat validation, and old-environment pruning covered with filesystem tests and mocked system commands |
| Static checks | Python compilation, JavaScript syntax, and `git diff --check` passed |

## Review fixes completed on 2026-09-16

- Installer optional commands now report nonzero exit codes correctly. A failed
  stop of an active service prevents environment activation.
- Rollback captures configuration after services stop, preserving settings saved
  by the portal during shutdown.
- Invalid configuration reloads raise an error so the controller retains its
  settings. A failed menu mode save neither overwrites broken configuration nor
  exits playback.
- Failed or structurally invalid API responses preserve the last saved feed;
  explicit empty schedule lists are still accepted. Invalid rows and null
  containers no longer discard valid records elsewhere in the feed. All matching
  screen groups are processed and duplicate slots remain deduplicated.
- Cache lookups tolerate files disappearing during background cleanup.
- README, architecture, setup, and portal documentation now describe mpv,
  current configuration behavior, and the installer rollback limits.

These fixes add 14 regression checks to the original 61. The full real-mpv
integration test was rerun after the code changes. Latest rendering artifacts
are in `/tmp/eposter-review-validation-1080p/` and
`/tmp/eposter-review-validation-4k/`; each contains `result.txt`, screenshots,
and logs. They are temporary local artifacts, not committed test fixtures.

The transition metric samples the center pixel of synthetic colored media. It
can detect full-screen black frames in this test sequence; it does not prove
that every pixel remains identical or that HDMI behavior on every board is
correct. Temporary screenshots and capture results are written by the visual
test to `/tmp/eposter-playback-validation/` by default.

## Reproduce

```sh
python3 -m unittest discover -s tests -v
python3 tools/playback_smoke.py --integration
python3 tools/playback_smoke.py --visual --xvfb /path/to/Xvfb
python3 tools/playback_smoke.py --visual --resolution 3840x2160 --xvfb /path/to/Xvfb --output /tmp/eposter-playback-validation-4k
```

The integration test uses a temporary loopback HTTP server, separate config/API
files, and a temporary cache. The visual test starts its own X server, opens no
window on the normal desktop, and does not change the physical display mode.
Both require local socket access. The installer runs the shorter
`tools/playback_smoke.py --quick` check as the display user before activating the
new Python environment.

## Fullscreen and UHD follow-up

Still images now resize to the media area above the reserved footer without
letterboxing or cropping. Different aspect ratios stretch; embedded margins in source files
remain part of the source. Paper ID/address text uses 32 px at 1080p and 64 px at
UHD, with a proportional footer and countdown. The opaque footer is 56 px at
1080p and 112 px at UHD, with Paper ID aligned left and the address aligned
right. mpv reserves the corresponding video margin after rotation; image
preparation uses the smaller media area so the full poster remains visible.
The menu already leaves room for the footer and uses the full window.
The desktop must already be configured for UHD output; the app does not switch
HDMI modes between files. Video/GIF aspect handling and the disk cache are unchanged.

Footer validation checks the actual video rectangle at all four rotations,
retention of a colored marker at the poster's bottom edge above the footer,
an opaque footer background, and left/right text positions in rendered frames.

The longer capture exposed intermittent blank video intervals with the legacy
`gpu` renderer under software OpenGL, including with frame holding disabled.
Desktop and explicit software-rendering checks prefer `gpu-next`; the final
1080p/UHD runs passed with it. ARM boards now select `gpu` directly following
reported Radxa `gpu-next/libplacebo` GL_INVALID_ENUM and GL_INVALID_OPERATION
errors with a missing footer. The previous `gpu-next,gpu` list did not help
because those errors occurred after initialization. This compatibility change
still requires visual validation on the target board; desktop checks do not
establish that the board's graphics driver works. The active renderer and display dimensions are reported
in `.playback-status.json` alongside the decoder.

The display now mutes outgoing audio, holds the outgoing frame, loads the next
file paused, removes the hold, and then resumes the replacement. Capture runs
until the complete sequence finishes and checks that every test media type was
actually observed. Cursor drawing is disabled in the recorder so the pointer
cannot obscure the sampled pixel. UHD capture samples at 15 fps to limit
software-renderer contention; it is not a 4K video throughput benchmark.

## On-board acceptance still required

- Run the full installer on one board from each hardware/OS family. The Debian
  package install and real systemd restart/permissions have not been executed on
  a board here. The installer validates its staged environment and requires a
  fresh ready-player heartbeat after restart.
- Check `journalctl -u eposter-display.service` or `.playback-status.json` for
  the decoder actually used. `video_hwdec=auto` is a preference, not proof of
  hardware decoding. Rockchip `rkmpp` requires a compatible mpv/FFmpeg/driver build.
- Use representative production codecs, resolutions, audio tracks, and portrait
  media. Observe image→video, video→image, video→video, GIFs, and loop boundaries
  on the physical monitor. Confirm there is no HDMI signal loss.
- Confirm all boards use synchronized clocks and the same `api.timezone` when
  API timestamps have no timezone offset.
- Run an extended playlist, restart mid-slot, and interrupt network access.
  Confirm countdowns follow the API end time and already cached media continues.

## Update behavior

The existing webpage updater still runs the full `installer.py`. The installer
adds mpv/fonts, stages dependencies in `.venvs/`, checks them before stopping the
services, backs up and migrates config, activates the new environment, and
restarts the services. Existing cache files are retained. Activation failures
restore the previous environment/config and restart services. Source-code pulls
and OS-package transactions are not automatically rolled back.

The service currently targets the existing X11 session on `:0`. A Wayland-only
board needs a corresponding service/session setup. Frame holding depends on the
video output's window screenshot support; if unavailable, the persistent mpv
window's keep-open behavior remains the fallback.

## Menu shortcuts

Press `m` or `M` during playback to open the poster library. Use Up/Down or
Page Up/Page Down to browse, and Enter/Space or a tap to preview. `M` returns
from a preview to the library. Escape returns from a preview to the library;
Escape in the library or Start schedule resumes scheduled playback. Mode
changes are saved so configuration refreshes do not undo keyboard navigation.

The menu uses outlined selection cards, media thumbnails, and uniform Paper ID
labels. Pillow previews were checked in portrait and landscape; live Radxa
rendering and its audio/video synchronization still require device validation.

## Memory optimization (September 17, 2026)

Opaque poster preparation now avoids the RGBA/compositing path and closes
intermediate images promptly. Transition holds clear the rotated footer in one
RGBA buffer instead of allocating a mask and another full-screen buffer.
Uploading an RGBA hold avoids another conversion copy; temporary PNG/BGRA files
are removed after use. mpv compressed packet limits are 32 MiB forward and
4 MiB backward for local media; these limits do not cap decoded frames or GPU RAM.

A fresh-process Python workload prepared a 3840x2160 RGB PNG at 3840x2016,
then created and closed 3840x2160 frame holds at all four rotations. Linux
resource.getrusage(resource.RUSAGE_SELF).ru_maxrss decreased from 186672 KiB
to 122484 KiB (about 34%). This is a local synthetic Python peak, not a
measurement of total Radxa memory or a promise of video memory savings.
94 unit tests and the real mpv headless playback/looping check passed.

For a device comparison, replay the same media after restarting the app and use:

```sh
free -h
ps -eo pid,comm,rss,%mem,args --sort=-rss | head -15
vmstat 1 10
```

RSS is in KiB and can include shared pages; free reports the entire system.
Compare available memory and sustained swap-in/swap-out, not free memory alone.
A nonzero amount of allocated swap does not by itself show current swap activity.

## Radxa ZERO 3 playback profile

To use the settings from the user's improved 1080x1920/59.94fps test, set these
fields within the existing `display` object in the board's `config.json`:

```json
"video_profile": "radxa-zero3",
"video_hwdec": "rkmpp"
```

Restart the app after changing the profile or audio setting. This profile selects
`gpu`, OpenGL, `profile=fast`, `swapchain-depth=8`, `opengl-swapinterval=0`, and
`x11-bypass-compositor=yes`. The player already runs fullscreen. An `auto`
decoder setting resolves to `rkmpp` only with this explicit profile; explicit
values such as `no` or `rkmpp-copy` are preserved. The default profile retains
previous renderer selection for other devices.

`video_audio` defaults to `true`. Set it to `false` for silent playback matching
the successful command-line test. Audio is disabled at track selection, so
transition unmuting cannot reactivate it. Audio-on performance remains unverified
because the device reported a PipeWire timeout during the earlier audio test.

The user's swapchain-depth test dropped 248 frames; disabling OpenGL vsync
waiting reduced that to 129, and the user reported visibly better playback.
This is improved playback, not zero-drop validation. Disabling vsync can cause
tearing and the larger queue trades memory/latency for better pipelining.
Validate the full app with its footer, rotation, and transitions on the board.
`.playback-status.json` now includes rendering and decoder dropped-frame counts
for the current media, alongside the active decoder and renderer.
