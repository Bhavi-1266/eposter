#!/usr/bin/env python3
"""Headless real-mpv checks. No HDMI window, API access, or cache changes."""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops
from helper.mpv_player import MpvPlayer, PlayerError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--integration', action='store_true', help='Also exercise the real local API/cache/controller flow')
    parser.add_argument('--visual', action='store_true', help='Test in a private Xvfb display')
    parser.add_argument('--xvfb', default='Xvfb')
    parser.add_argument('--resolution', default='960x540', choices=['960x540', '1920x1080', '3840x2160'], help='Virtual display resolution for --visual')
    parser.add_argument('--output', default='/tmp/eposter-playback-validation')
    args = parser.parse_args()
    if args.visual:
        return visual_test(args)
    player = MpvPlayer(headless=True)
    try:
        pid = player.proc.pid
        first, second, gif = [player.directory/name for name in ('first.png', 'second.png', 'animation.gif')]
        Image.new('RGB', (320, 180), 'red').save(first)
        Image.new('RGB', (180, 320), 'blue').save(second)
        Image.new('RGB', (64, 64), 'green').save(gif, save_all=True, append_images=[Image.new('RGB', (64,64), 'yellow')], duration=100, loop=0)
        for path, rotation in ((first,0),(second,90),(gif,180),(first,270)):
            player.load(path, rotation)
            assert player.proc.pid == pid
            assert player.command('get_property', 'video-rotate') == rotation
        player.set_overlay(deadline=int(time.time())+60, rotation=0, footer_left='Paper ID: 1', footer_right='192.0.2.10', status='')
        time.sleep(.2)
        remaining = int(player.properties.get('eposter-countdown'))
        assert 58 <= remaining <= 60, remaining
        import subprocess
        video = player.directory/'clip.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=red:s=160x90:r=10','-t','0.4','-c:v','mpeg4',str(video)], check=True, timeout=15)
        player.load(video, start_paused=True)
        assert player.command('get_property', 'pause') is True
        player.command('set_property', 'pause', False)
        restarts = player.playback_restarts
        time.sleep(0.1 if args.quick else 1)
        assert player.alive and player.proc.pid == pid
        if not args.quick:
            assert player.playback_restarts > restarts, "Short video did not loop"
            assert 50 <= int(player.properties['eposter-countdown']) < remaining
        player.load(second)
        bad = player.directory/'broken.mp4'
        bad.write_bytes(b'not a video')
        try:
            player.load(bad, timeout=3)
        except PlayerError:
            pass
        else:
            raise AssertionError('Broken media was accepted')
        player.load(first)
        player.proc.kill()
        player.proc.wait(timeout=3)
        try:
            player.command('get_property', 'path')
        except PlayerError:
            pass
        else:
            raise AssertionError('Disconnected player was reported healthy')
        print('PASS: real mpv images/GIFs/video, rotation, persistent process, IPC and corrupt-file recovery' + ('' if args.quick else ', video looping'))
    finally:
        player.close()
    assert player.proc.poll() is not None
    if args.integration:
        controller_test()


def controller_test():
    import json
    import threading
    import tempfile
    import subprocess
    from datetime import datetime, timezone
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from unittest.mock import patch
    import RunThis
    from helper import api_handler, cache_handler, wifi_connect
    from helper.configuration import load_config, migrate_config
    from helper.media_controller import Controller
    from helper.display_handler import Display
    with tempfile.TemporaryDirectory(prefix='eposter-end-to-end-') as tmp:
        root=Path(tmp)
        media=root/'source'
        media.mkdir()
        Image.new('RGB',(320,180),'red').save(media/'poster.png')
        Image.new('RGB',(320,180),'green').save(root/'ScreenSaver.png')
        Image.new('RGB',(64,64),'green').save(media/'animation.gif',save_all=True,append_images=[Image.new('RGB',(64,64),'yellow')],duration=100,loop=0)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=160x90:r=10','-t','0.4','-c:v','mpeg4',str(media/'video.mp4')],check=True,timeout=15)
        now=int(time.time())
        feed={'screens':[{'screen_number':7,'records':[]}]}
        def stamp(value):
            return datetime.fromtimestamp(value,timezone.utc).isoformat()
        downloads=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith('/api'):
                    data=json.dumps(feed).encode()
                else:
                    name=Path(self.path).name
                    downloads.append(name)
                    data=(media/name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self,*args):
                pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server_thread=threading.Thread(target=server.serve_forever,daemon=True)
        server_thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        for index,name in enumerate(('poster.png','video.mp4','animation.gif')):
            feed['screens'][0]['records'].append({'id':index,'paper_id':index,'file':base+'/media/'+name,'start_date_time':stamp(now-1+index*3),'end_date_time':stamp(now+2+index*3),'duration_seconds':1})
        config={'display':{'device_id':7,'Mode':'Time','rotation_degree':0,'cache_refresh':30},'api':{'poster_api_url':base+'/api/posters','timezone':'UTC'},'wifi':{}}
        config_path=root/'config.json'
        config_path.write_text(json.dumps(config))
        migrate_config(config_path)
        player=MpvPlayer(headless=True)
        display=Display(player=player)
        controller=None
        failure=[]
        patches=[patch.object(RunThis,'CONFIG_FILE',config_path),patch.object(RunThis,'API_DATA_JSON',root/'api_data.json'),patch.object(api_handler,'ROOT_DIR',root),patch.object(api_handler,'API_DATA_JSON',root/'api_data.json'),patch.object(cache_handler,'ROOT_DIR',root),patch.object(cache_handler,'CACHE_DIR',root/'eposter_cache'),patch.object(wifi_connect,'ensure_wifi_connection',return_value=True)]
        try:
            for p in patches: p.start()
            controller=Controller(root,lambda:load_config(config_path),RunThis.get_device_records,RunThis.refresh_data_and_cache,lambda _:None,display)
            def run():
                try: controller.run()
                except Exception as error: failure.append(error)
            thread=threading.Thread(target=run,daemon=True)
            thread.start()
            pid=player.proc.pid
            seen=set()
            end=time.monotonic()+10
            refreshed=False
            while time.monotonic()<end and thread.is_alive():
                path=player.properties.get('path') or ''
                if path.endswith('.mp4'): seen.add('video')
                if path.endswith('.gif'): seen.add('gif')
                cached_poster=cache_handler.get_media_path(base+'/media/poster.png')
                if cached_poster and display.shown and display.shown[0]==str(cached_poster): seen.add('image')
                if 'video' in seen and not refreshed:
                    from helper.media_controller import refresh_key
                    controller.worker.request(refresh_key(controller.config))
                    refreshed=True
                assert player.proc.pid==pid
                state=display.overlay_state or {}
                for paper in range(3):
                    if state.get('footer_left','') == f'Paper ID: {paper}':
                        assert state.get('deadline')==now+2+paper*3, state
                time.sleep(.05)
            controller.running=False
            thread.join(5)
            assert not thread.is_alive()
            assert not failure, failure
            assert seen=={'image','video','gif'},seen
            assert sorted(downloads)==['animation.gif','poster.png','video.mp4'],downloads
            assert json.loads(config_path.read_text())['display']['screen_number']==7
            assert len(list((root/'eposter_cache').glob('*')))==3
            print('PASS: actual HTTP API -> unchanged cache -> scheduler -> persistent player; API deadlines; unchanged refresh does not redownload; identifier migration')
        finally:
            if controller: controller.running=False
            display.close()
            for p in reversed(patches): p.stop()
            server.shutdown()
            server.server_close()


def visual_test(args):
    import logging
    import os
    import select
    import signal
    import subprocess
    from helper.display_handler import Display, footer_height, overlay_scale
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'result.txt').unlink(missing_ok=True)
    logging.basicConfig(filename=output/'display.log', filemode='w', level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', force=True)
    read_fd, write_fd = os.pipe()
    log = (output/'xvfb.log').open('w')
    screen_size = tuple(map(int, args.resolution.split('x')))
    xvfb = subprocess.Popen([args.xvfb, '-displayfd', str(write_fd), '-screen', '0', args.resolution+'x24', '-nolisten', 'tcp', '-ac'], pass_fds=(write_fd,), stdout=log, stderr=log)
    os.close(write_fd)
    player = display = None
    try:
        if not select.select([read_fd], [], [], 10)[0]:
            raise RuntimeError('Virtual display did not start; check xvfb.log')
        display_name = ':' + os.read(read_fd, 64).decode().strip()
        os.environ['DISPLAY'] = display_name
        os.environ.pop('WAYLAND_DISPLAY', None)
        os.environ['XDG_SESSION_TYPE'] = 'x11'
        player = MpvPlayer(hwdec='no', software_rendering=True)
        display = Display(player=player)
        first, second, gif, video = [output/name for name in ('first.png','second.png','animation.gif','clip.mp4')]
        poster = Image.new('RGB',(960,540),(180,40,50))
        poster.paste((20,180,60), (0,520,960,540))
        poster.save(first)
        Image.new('RGB',(960,540),(40,60,180)).save(second)
        Image.new('RGB',(160,90),(30,140,30)).save(gif, save_all=True, append_images=[Image.new('RGB',(160,90),(160,160,30))], duration=200, loop=0)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=25','-t','0.6','-c:v','mpeg4',str(video)],check=True,timeout=15)
        def show(path, rotation=0, menu=None):
            display.show(path,rotation,menu)
            end = time.monotonic()+12
            while display.shown != display.requested:
                if display.error:
                    raise AssertionError(display.error)
                if time.monotonic()>end:
                    raise AssertionError('Display transition timed out')
                time.sleep(.02)
        deadline = int(time.time())+120
        display.overlay(deadline=deadline, paper_id='Test 42', ip='192.0.2.10', rotation=0)
        show(first)
        time.sleep(.4)
        window = player.command('get_property','window-id')
        pid = player.proc.pid
        assert display.size == screen_size, (display.size, screen_size)
        capture_fps = 15 if screen_size[0] >= 3840 else 60
        recording = subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-f','x11grab','-draw_mouse','0','-video_size',args.resolution,'-framerate',str(capture_fps),'-i',display_name,'-t','60','-vf','scale=160:90','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        # Drain concurrently: raw-frame pipes otherwise block recording.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            recorded = pool.submit(recording.communicate)
            try:
                for path in (video,second,gif,video,first):
                    show(path)
                    logging.info('Transition completed: %s', path.name)
                    time.sleep(.9 if path == video else .5)
                    assert player.proc.pid == pid
                    assert player.command('get_property','window-id') == window
                    assert player.command('get_property','mute') is False
                    assert player.command('get_property','pause') is False
            finally:
                recording.send_signal(signal.SIGINT)
                raw, errors = recorded.result(timeout=12)
        assert recording.returncode in (0,255), errors.decode()
        frame_bytes = 160*90*3
        frames = len(raw)//frame_bytes
        dark = 0
        seen_colors = set()
        sheet = Image.new('RGB',(160*10,90*((frames+9)//10)))
        for index in range(frames):
            frame = Image.frombytes('RGB',(160,90),raw[index*frame_bytes:(index+1)*frame_bytes])
            sheet.paste(frame, ((index%10)*160,(index//10)*90))
            if max(frame.getpixel((80,45))) < 15:
                dark += 1
            r,g,b = frame.getpixel((80,45))
            if r > 130 and g < 80 and b < 80: seen_colors.add('first')
            if b > 130 and 20 < r < 80 and 30 < g < 100: seen_colors.add('second')
            if b > 200 and r < 20 and g < 20: seen_colors.add('video')
            if g > 100 and b < 80: seen_colors.add('gif')
        assert frames >= capture_fps*2, frames
        sheet.save(output/'transition-frames.jpg')
        assert seen_colors == {'first','second','video','gif'}, seen_colors

        def color_mask(image, color):
            diff = ImageChops.difference(image.convert('RGB'), Image.new('RGB', image.size, color))
            bands = [band.point(lambda v: 255 if v < 4 else 0) for band in diff.split()]
            return ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])

        def check_timer(logical, state):
            w, h = logical.size
            strip = footer_height(screen_size)
            footer = logical.crop((0, h-strip, w, h))
            background, foreground = {'normal': ((255,255,255), (0,0,0)),
                                      'warning': ((254,240,138), (0,0,0)),
                                      'urgent': ((185,28,28), (0,0,0))}[state]
            bounds = color_mask(footer, background).getbbox()
            assert bounds, ('Missing countdown background', state)
            x0, y0, x1, y1 = bounds
            scale = overlay_scale(screen_size)
            assert abs((x0+x1)/2-w/2) <= 2*scale, ('Timer not horizontally centered', bounds)
            assert abs((y0+y1)/2-strip/2) <= 2*scale, ('Timer not vertically centered', bounds)
            digits = footer.crop(bounds)
            ink = color_mask(digits, foreground).getbbox()
            assert ink, 'Missing countdown text'
            assert ink[3]-ink[1] >= 26*scale, ('Countdown text too small', ink)
            assert abs((ink[0]+ink[2])/2-digits.width/2) <= 3*scale, ('Digits not centered', ink)
            # ASS aligns line boxes; visible digits should also be near center.
            assert abs((ink[1]+ink[3])/2-digits.height/2) <= 5*scale, ('Digits not vertically centered', ink)

            assert digits.getpixel((0, 0)) == (245,245,245), 'Timer corners are not rounded'
            return ink[3]-ink[1]

        for rotation in (0,90,180,270):
            display.overlay(deadline=int(time.time())+180,paper_id='3263',ip='192.0.2.10',rotation=rotation)
            show(video,rotation)
            # Check the actual renderer's video rectangle excludes the footer.
            dimensions = player.command('get_property','osd-dimensions')
            side = {0:'mb',90:'ml',180:'mt',270:'mr'}[rotation]
            assert dimensions[side] >= footer_height(screen_size)-1, (rotation,dimensions)
            show(first,rotation)
            time.sleep(.25)
            player.command('screenshot-to-file',str(output/f'overlay-{rotation}.png'),'window')
            with Image.open(output/f'overlay-{rotation}.png') as snapshot:
                assert snapshot.size == screen_size, snapshot.size
                logical = snapshot.rotate(rotation, expand=True).convert('RGB')
                w, h = logical.size
                strip = footer_height(screen_size)
                # The entire poster, including its green bottom edge, must fit
                # above the footer in every orientation.
                for point in ((w//2, 1), (1, h//2), (w-2, h//2)):
                    pixel = logical.getpixel(point)
                    assert max(abs(a-b) for a,b in zip(pixel, (180,40,50))) < 8, (rotation, point, pixel)
                pixel = logical.getpixel((w//2,h-strip-3))
                assert max(abs(a-b) for a,b in zip(pixel,(20,180,60))) < 8, (rotation,pixel)
                assert logical.getpixel((w//2,h-strip+2)) == (245,245,245)
                footer = logical.crop((0,h-strip,w,h)).convert('L')
                ink = footer.point(lambda value: 255 if value < 150 else 0)
                assert ink.crop((0,0,w//4,strip)).getbbox(), 'Missing left Paper ID'
                right = ink.crop((w*3//4,0,w,strip)).getbbox()
                assert right, 'Missing right address'
                right_gap = w-(w*3//4+right[2])
                assert 8*overlay_scale(screen_size) <= right_gap <= 32*overlay_scale(screen_size), (rotation,right_gap)
                normal_height = check_timer(logical, 'normal')
            for name, remaining in (('warning', 120), ('urgent', 60), ('expired', 0)):
                display.overlay(deadline=int(time.time())+remaining,paper_id='3263',ip='192.0.2.10',rotation=rotation)
                time.sleep(.15)
                filename = output/f'timer-{name}-{rotation}.png'
                player.command('screenshot-to-file',str(filename),'window')
                with Image.open(filename) as snapshot:
                    height = check_timer(snapshot.rotate(rotation,expand=True).convert('RGB'),
                                         'warning' if name == 'warning' else 'urgent')
                    if name != 'warning':
                        assert height > normal_height, 'Final-minute digits did not grow'
        menu={'key':(1,0,0),'items':[{'path':first,'paper_id':42},{'path':video,'paper_id':43}], 'offset':0,'selected':0}
        display.overlay(ip='192.0.2.10',rotation=0,menu=True)
        show(None,0,menu)
        time.sleep(.2)
        player.command('screenshot-to-file',str(output/'menu.png'),'window')
        player.command('keypress','ENTER')
        time.sleep(.1)
        assert any(event[0]=='ENTER' for event in display.inputs())
        remaining = player.properties.get('eposter-countdown')
        assert remaining == '', remaining
        with Image.open(output/'menu.png') as snapshot:
            footer = snapshot.crop((0,screen_size[1]-footer_height(screen_size),screen_size[0],screen_size[1]))
            assert color_mask(footer, (185,28,28)).getbbox() is None
            assert color_mask(footer, (248,240,222)).getbbox() is None
        assert dark == 0, f'{dark}/{frames} frames went black at the center'
        (output/'result.txt').write_text(f'PASS: {args.resolution}; {frames} captured transition frames at {capture_fps} fps, {dark} black center frames; all test media observed; same window {window} and PID {pid}; reserved footer, centered large timer, white/yellow/red/expired states, left Paper ID/right address at four rotations; menu input and no unscheduled timer.\n')
        print((output/'result.txt').read_text())
    finally:
        if display:
            display.close()
        elif player:
            player.close()
        os.close(read_fd)
        xvfb.terminate()
        xvfb.wait(timeout=5)
        log.close()


if __name__ == '__main__':
    main()
