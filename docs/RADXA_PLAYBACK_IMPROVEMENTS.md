# Radxa ZERO 3: playback improvements and setup guide

Recorded: September 17, 2026.

This guide collects the changes made to ePoster, the tests performed on the
Radxa, and the instructions for enabling the improved playback settings.
The user reported smoother playback with the final command, but the last
reported result was 129 dropped frames. Zero-drop playback and the complete
updated app still need validation on the board.

## Completion checklist

The requested application work is implemented in this workspace:

- [x] Preserve and display the API's actual Paper ID.
- [x] Show `Paper ID: 12342` on one line at one consistent size.
- [x] Use a professional footer with balanced spacing and a top divider.
- [x] Give the timer a rounded white background with black text.
- [x] Change the timer to yellow at two minutes and red with larger text at
  one minute.
- [x] Redesign the menu and bind both `m` and `M` to open it.
- [x] Align `config.json` fields with `config.example.json` while preserving
  device-specific values.
- [x] Remove the unrelated `output.png` file.
- [x] Add the Radxa ZERO 3 hardware-decoding playback profile.
- [x] Reduce image/transition memory allocations and bound mpv packet buffers.
- [x] Add playback status counters and automated coverage.
- [x] Pass all 94 local unit tests.
- [ ] Deploy the workspace changes to the Radxa and validate the full app on
  its physical display. This final item must be performed on the board.

### Short deployment and verification sequence

After the changes are available on the board, use this order:

1. Pull or copy the updated project into `/home/rock/eposter`.
2. Add `video_profile`, `video_hwdec`, and `video_audio` to the existing
   `display` object in `config.json`, as shown in section 2.
3. Validate the configuration with
   `python3 -m json.tool config.json >/dev/null`.
4. Confirm that HDMI uses progressive `1920x1080` at 60 Hz with
   `xrandr --current`.
5. Restart only the installed ePoster service, or run `python RunThis.py` if
   the app is operated manually.
6. During an actual video, confirm `hardware_decoder` is `rkmpp` in
   `.playback-status.json`.
7. Check smoothness, tearing, footer visibility, timer colors, Paper IDs, and
   the `M`, Enter, and Esc menu controls over a complete playlist cycle.

## 1. Confirmed hardware and software

The board identifies itself as **Radxa ZERO 3**, using Rockchip RK3566.
The supplied diagnostic output showed:

| Component | Reported value |
| --- | --- |
| OS | Debian GNU/Linux 12 (Bookworm) |
| Kernel | `6.1.84-13-rk2410-nocsf` |
| mpv | `v0.39.0-dev-g8d2ed139c`, built June 26, 2025 |
| FFmpeg linked to mpv | `f37c17d024` |
| GPU renderer | `Mali-G52 r1 (Panfrost)` |
| Graphics session | X11, using EGL/OpenGL |
| Test video | H.264, 1080×1920 portrait, 59.9401 fps, approximately 13 seconds |
| Test audio | PCM 24-bit, stereo, 48 kHz |

Radxa lists 1080p60 HDMI output and separately lists H.264/H.265 decoding up
to 4K60 in its product brief. These specifications do not document a
zero-drop mpv benchmark for this particular software stack or file.

## 2. Enable the improved settings in ePoster

### Update the application code

The changes must be copied to the board, or published to its Git remote before
pulling them. This guide does not imply that the workspace changes have already
been committed or pushed.

If the changes are available on `origin/main`, run from the board:

```bash
cd /home/rock/eposter
git status --short
git pull --ff-only origin main
```

Resolve any reported local-edit conflicts without discarding device settings.
These playback changes do not require replacing the board's working
Rockchip-enabled mpv/FFmpeg installation.

### Configure the Radxa profile

Edit the board's existing `config.json`. Add or update these fields **inside
the existing `display` object**, preserving its other fields:

```json
{
  "video_profile": "radxa-zero3",
  "video_hwdec": "rkmpp",
  "video_audio": false
}
```

The object above is a display-settings excerpt, not a replacement for the whole
configuration file. Keep the existing API URLs, credentials, screen number,
rotation, mode, and schedule settings.

- `video_audio: false` reproduces the silent test that improved playback.
- Use `video_audio: true` if sound is required. Audio-on performance remains
  unverified; earlier tests reported a PipeWire initialization timeout.
- Audio defaults to `true` when omitted. The new profile does not silently
  disable sound.
- With this profile, `video_hwdec: auto` also resolves to `rkmpp`. Explicit
  overrides such as `no` and `rkmpp-copy` remain supported.
- The generic `config.example.json` keeps `video_profile: default` so unrelated
  devices do not receive Radxa-specific tuning.

Validate JSON syntax:

```bash
python3 -m json.tool config.json >/dev/null
```

### Restart the application

Profile and audio changes require restarting the app. Use the method that
matches how the board runs ePoster; avoid running a manual instance alongside
the display service.

For the installed systemd service:

```bash
sudo systemctl restart eposter-display.service
journalctl -u eposter-display.service -n 80 --no-pager
```

For manual operation, stop the existing app with `q` in its window or Ctrl+C
in its terminal, then run in the same Python environment used previously:

```bash
cd /home/rock/eposter
python RunThis.py
```

## 3. What the Radxa profile changes

| Setting | Purpose |
| --- | --- |
| `--vo=gpu` | Uses the renderer that avoided the reported `gpu-next/libplacebo` GL errors |
| `--gpu-api=opengl` | Keeps the confirmed Panfrost OpenGL rendering path |
| `--hwdec=rkmpp` | Explicitly selects Rockchip hardware decoding |
| `--profile=fast` | Reduces rendering work |
| `--swapchain-depth=8` | Allows more frames in flight, trading memory/latency for pipelining |
| `--opengl-swapinterval=0` | Disables OpenGL vsync waiting; this gave the largest improvement in the later tests |
| `--x11-bypass-compositor=yes` | Requests compositor bypass; the window manager decides whether to honor it |
| Fullscreen | Already used by ePoster |

Disabling vsync may cause horizontal tearing. Check visible motion, not only
the dropped-frame count. The larger queue can increase memory use and latency;
it is a playback tradeoff, not a memory optimization.

ePoster starts mpv with `--no-config`. Editing `~/.config/mpv/mpv.conf` alone
will therefore not change the application's player settings.

## 4. Working standalone test command

Stop ePoster before testing so a second player does not compete for resources.
Run this command once; do not paste two copies onto the same command line.

```bash
mpv --no-config --profile=fast --fullscreen --x11-bypass-compositor=yes --vo=gpu --gpu-api=opengl --hwdec=rkmpp --audio=no --swapchain-depth=8 --opengl-swapinterval=0 "/home/rock/eposter/eposter_cache/8d3ff31b37aa6f038d0a7c3ce4502eec78fe7ec6.mov"
```

That cache path belongs to the tested file. Replace it if the schedule/cache
changes. This command checks video playback only; it does not load the app's
footer, countdown, menu, or schedule controller.

## 5. Tests performed and results

The following are user-reported results for the same short video. They are
single runs, not averaged benchmarks, and some runs changed window geometry.

| Test | Dropped frames | Finding |
| --- | ---: | --- |
| Explicit `rkmpp`, audio enabled | 558 | Hardware decoding worked; audio timeout/desynchronization remained |
| `rkmpp`, audio disabled | 527 | Audio was not the only bottleneck |
| Add `--profile=fast` | 242 | Lower rendering cost helped substantially |
| Switch HDMI from interlaced to progressive, retain fast profile | 242 | Mode change alone did not improve this count |
| `rkmpp-copy`, fast profile, no audio | 321 | Copy-back performed worse than direct `rkmpp` |
| `rkmpp`, fast profile, fullscreen/compositor bypass | 256 | No material improvement over the earlier fast-profile run |
| Add `--swapchain-depth=8` | 248 | Small change in this run |
| Add `--opengl-swapinterval=0` | 129 | About 48% fewer drops than 248; user reported smoother playback |

The evidence suggests rendering/presentation timing contributes to the issue.
It does not establish the exact driver-level cause or prove that decoding,
memory bandwidth, temperature, and system load never contribute.

## 6. Confirm acceleration and display mode

### Hardware and decoder inventory

Run these on the Radxa, not the development computer:

```bash
tr -d '\0' </proc/device-tree/model
cat /etc/os-release
uname -r
mpv --version
mpv --hwdec=help
mpv --vd=help | grep -Ei 'rkmpp|v4l2|h264|hevc'
```

The board's mpv lists `h264_rkmpp`, `hevc_rkmpp`, `rkmpp`, and `rkmpp-copy`.
Listing a decoder means it is available in the build, not necessarily active.
Successful standalone playback reported:

```text
Using hardware decoding (rkmpp).
VO: [gpu] 1080x1920 drm_prime[nv12]
GL_RENDERER='Mali-G52 r1 (Panfrost)'
```

The app should report `Video decoder: rkmpp`. `Video decoder: no` means
software decoding for the active video. `software / no video` can also appear
between files, so inspect the state while a video is actually playing.

### Progressive HDMI output

The display initially selected `1920x1080i` (interlaced). It was changed to
the supported progressive mode with:

```bash
xrandr --output HDMI-1 --mode 1920x1080 --rate 60
xrandr --current
```

The `*` should appear beside `60.00` on the `1920x1080` row, not the
`1920x1080i` row. This command applies to the current X11 session; persistence
across login/reboot was not configured. Save the mode through the desktop's
display settings if needed. ePoster does not automatically change HDMI modes.

## 7. Memory optimizations implemented

- Opaque posters use RGB preparation without an unnecessary RGBA canvas.
- Large intermediate images are closed promptly.
- Transition footer cutouts are cleared directly in one RGBA image, avoiding
  a rotated full-screen mask and another full-screen image.
- Already-RGBA transition images are not copied again during bitmap upload.
- Temporary transition PNG/BGRA files are removed after use.
- mpv compressed packet buffers are limited to **32 MiB forward** and
  **4 MiB backward**. These are not limits on total player RAM, decoded frames,
  or GPU memory.

A local synthetic 4K image/transition workload decreased from **186672 KiB
to 122484 KiB peak Python RSS**, approximately **182 MiB to 120 MiB**, or 34%.
This was not a measurement of the Radxa's total memory or its video workload.

The user's system-wide screenshots showed 806 MiB available during image
display and 568 MiB during video playback. Low `free` memory alone does not
mean Linux has exhausted usable memory; compare `available` and active swapping.

```bash
free -h
ps -eo pid,comm,rss,%mem,args --sort=-rss | head -15
vmstat 1 10
```

RSS is in KiB and includes shared pages. For `vmstat`, examine subsequent
samples for sustained `si`/`so` activity; allocated swap alone does not prove
the system is currently swapping heavily.

## 8. Footer, paper IDs, menu, and configuration changes

### Paper IDs and footer

- Use the API's actual `paper_id`, preserving leading zeros and numeric zero.
- Keep distinct papers separate even if they share the same media URL.
- Associate menu/scroll previews with the matching paper's deadline.
- Display `Paper ID: 12342` as one continuous line at one consistent size.
- Use balanced side padding, a subtle top divider, a smaller secondary IP
  address, and a centered timer with rounded corners and a fine outline.
- Reserve a footer strip outside the media viewport, including after rotation.
  The current base height is 72 pixels at 1080p, scaled with the display.

### Timer

| Time remaining | Appearance |
| --- | --- |
| More than 2 minutes | White background, black digits |
| 2 minutes or less, above 1 minute | Yellow background, black digits |
| 1 minute or less | Red background, larger black digits |

Countdown deadlines remain tied to the API schedule rather than video length.

### Menu

The updated menu uses poster cards, media thumbnails, a purple selection
outline, readable paper IDs, media-type labels, and keyboard hints.

| Control | Action |
| --- | --- |
| `m` or `M` during playback | Open the menu |
| `M` during a preview | Return to the menu |
| Up/Down or mouse wheel | Browse posters |
| Page Up/Page Down | Browse a page at a time |
| Enter/Space or tap a poster | Open a preview |
| Esc during preview | Return to the menu |
| Esc in the menu or Start schedule | Resume scheduled Time mode |
| `q` | Quit the application |

Mode changes are saved so configuration reloads do not undo menu navigation.
Opening the menu and then choosing Start schedule resumes Time mode, even if
the original mode was Scroll.

### Configuration and cleanup

`config.json` was aligned with example fields while preserving device values.
The example now also documents `video_profile` and `video_audio`. The unrelated
`output.png` was removed. Do not replace a board's live config with the example:
the example contains placeholders and generic playback defaults.

## 9. Errors investigated separately

| Message | Meaning and status |
| --- | --- |
| `gpu-next/libplacebo` GL errors | Occurred with missing footer; ARM playback now selects `gpu`, and the subsequent supplied run no longer showed those repeated errors |
| `Video decoder: no` | Software decoding; explicitly selecting `rkmpp` confirmed hardware decoding on this board |
| Missing `libvdpau_rockchip.so` | The attempted VDPAU path failed; working `rkmpp` does not require selecting VDPAU |
| PipeWire initialization timeout | Unresolved audio-path issue; successful later tests disabled audio |
| `libopenh264: DecodeFrame failed` | Earlier video-decoding failure; separate from HTTP download and GL rendering failures |
| HTTP 404 for media | Server reports the requested resource was not found; check/restore the file or correct its API URL |
| HTTP 422 for media | Server could not process the request; response body/server logs are needed for the specific reason |
| `Cannot open file 'mpv'` | Caused by pasting two mpv commands on one line; mpv interpreted the second executable name as a media filename |
| No key binding for `m` | The running version predated the new menu binding; update the Lua/controller files and restart |

The download screenshot had 108 unique media URLs and 98 ready files. Missing
files are retried on refresh; available files can still play. Scheduled missing
media shows a waiting status. Decoder/rendering tuning does not repair bad URLs.

## 10. Validate after deployment

While an actual video is playing:

```bash
cd /home/rock/eposter
python3 -m json.tool .playback-status.json
```

Check `hardware_decoder`, `video_renderer`, `dropped_frames`, and
`decoder_dropped_frames`. The heartbeat is periodic (normally about 30 seconds),
and counters describe the current media rather than a lifetime total. Short
clips may finish before their counters appear in a heartbeat.

Check an extended playlist for smooth motion, horizontal tearing, footer
visibility, rotation, correct IDs/countdowns, M/Enter/Esc behavior, and
image/video/GIF transitions. If sound is required, repeat with audio enabled.

Local verification after profile integration: **94 unit tests passed**, and
the real mpv headless image/GIF/video/rotation/looping/recovery check passed.
These checks do not reproduce the Radxa's graphics output. Later visual tests
could not run in the development environment because Xvfb was missing; menu
Pillow previews were inspected in portrait and landscape.

To reproduce automated checks where dependencies are installed:

```bash
python3 -m unittest discover -s tests
python3 tools/playback_smoke.py
python3 tools/playback_smoke.py --visual
```

The visual check requires Xvfb and uses a private virtual display. See
[Playback validation](PLAYBACK_VALIDATION.md) for earlier test history.

### Pending diagnostic if drops remain unacceptable

This decode-and-copy benchmark was proposed but no result has been supplied:

```bash
time mpv --no-config --vo=null --hwdec=rkmpp-copy --audio=no --untimed --framedrop=no "/home/rock/eposter/eposter_cache/8d3ff31b37aa6f038d0a7c3ce4502eec78fe7ec6.mov"
```

It displays no video. Verify that hardware decoding is active. Completion
well below the clip's approximately 13-second duration indicates sufficient
decode/copy throughput in that test; completion near or above it needs further
investigation. It does not measure the direct `rkmpp` rendering path.

## 11. Return to previous playback behavior

To remove the new tuning, change `video_profile` to `default` and restart.
Keep `video_hwdec: rkmpp` if hardware decoding is still desired. To also restore
automatic decoder selection, use `video_hwdec: auto`; on this board earlier
automatic selection fell back to software. Set `video_audio: true` to restore
audio. The default ARM renderer remains `gpu` after the compatibility fix.

## 12. Source references

- [Radxa ZERO 3 documentation](https://docs.radxa.com/en/zero/zero3)
- [ZERO 3W product brief](https://dl.radxa.com/zero3/docs/hw/3w/radxa_zero_3w_product_brief.pdf)
- [Radxa multimedia/MPP guide](https://docs.radxa.com/en/zero/zero3/app-development/rtsp)
- [Radxa tested OS images](https://docs.radxa.com/en/zero/zero3/download)
- [FFmpeg-Rockchip rendering guide](https://github.com/nyanmisaka/ffmpeg-rockchip/wiki/Rendering): recommends the fast profile and suggests a deeper swapchain for frame drops.
- [mpv reference manual](https://mpv.io/manual/stable/): hardware-decoder status, buffer limits, swapchain depth, and OpenGL vsync options.
- [Firsthand RK3566/PineTab 2 report](https://clehaxze.tw/gemlog/2023/09-17-hardware-accelerated-playback-on-pinetab2.gmi): related timing issue resolved on a different Wayland setup; not proof of the same cause on this Radxa/X11 installation.
- [Linux free manual](https://www.man7.org/linux/man-pages/man1/free.1.html)

Research did not establish an exact upstream bug matching all of this board's
versions. The settings above record measured improvement, not a confirmed
driver repair or a guarantee of 60 fps for every file.
