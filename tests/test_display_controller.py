import copy
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from helper.media_controller import Controller, RefreshWorker
from helper.display_handler import PreparedImages, render_menu, logical_size, logical_point, uncover_overlays, menu_geometry, media_size, media_margins, footer_height


def record(name='a', start=100, end=400, duration=10):
    return {'id':name, 'paper_id':name, 'file':name,
            'start_dt':datetime.fromtimestamp(start,timezone.utc),
            'end_dt':datetime.fromtimestamp(end,timezone.utc), 'duration_seconds':duration}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'display':{'screen_number':7,'Mode':'Time','rotation_degree':0,'Auto_Scroll':5},'api':{}}
        self.records=[record()]
        self.display=Mock(error=None,size=(960,540))
        self.display.inputs.return_value=[]
        self.controller=Controller(self.root,lambda:copy.deepcopy(self.config),lambda _: (self.records,5),Mock(),Mock(),self.display)
        self.controller.apply_config(self.config)
        self.lookup=patch('helper.media_controller.cache_handler.get_media_path',side_effect=lambda url:self.root/(str(url)+'.png'))
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.controller.rebuild_items()

    def test_api_deadline_not_duration_seconds(self):
        path,deadline,paper,_,_=self.controller.choose(250)
        self.assertEqual(deadline,400)
        self.assertEqual(paper,'a')
        self.controller.tick(250)
        self.assertEqual(self.display.overlay.call_args.kwargs['deadline'],400)

    def test_radxa_profile_keeps_hardware_decoder_during_config_reload(self):
        self.config['display']['video_profile'] = 'radxa-zero3'
        self.controller.apply_config(self.config)
        self.display.player.command.assert_called_with('set_property', 'hwdec', 'rkmpp')
        self.display.player.command.reset_mock()
        self.controller.apply_config(copy.deepcopy(self.config))
        self.display.player.command.assert_not_called()

    def test_same_schedule_refresh_does_not_restart_timer(self):
        self.controller.tick(200)
        self.controller.records=copy.deepcopy(self.records)
        self.controller.rebuild_items()
        self.controller.tick(260)
        self.assertEqual(self.display.overlay.call_args.kwargs['deadline'],400)

    def test_actual_paper_id_is_preserved_in_time_mode(self):
        for paper_id in ('003154', 0, 'P-3154'):
            with self.subTest(paper_id=paper_id):
                self.controller.records = [dict(record(), id=221, paper_id=paper_id)]
                self.controller.tick(200)
                self.assertEqual(self.display.overlay.call_args.kwargs['paper_id'], paper_id)

    def test_shared_media_keeps_distinct_papers_and_their_deadlines(self):
        self.controller.records = [dict(record(), paper_id='003154'),
                                   dict(record('b', 200, 500), file='a', paper_id='003155')]
        self.controller.rebuild_items()
        self.assertEqual([item['paper_id'] for item in self.controller.items], ['003154', '003155'])
        for mode in ('Menu', 'Scroll'):
            with self.subTest(mode=mode):
                self.config['display']['Mode'] = mode
                self.controller.apply_config(self.config)
                if mode == 'Menu':
                    self.controller.selected = 1
                    self.controller.input(['ENTER'], 250)
                else:
                    self.controller.scroll_index = 1
                self.controller.tick(250)
                overlay = self.display.overlay.call_args.kwargs
                self.assertEqual(overlay['paper_id'], '003155')
                self.assertEqual(overlay['deadline'], 500)

    def test_changed_api_deadline_takes_effect(self):
        self.controller.records=[record(end=500)]
        self.assertEqual(self.controller.choose(260)[1],500)

    def test_slot_expiry_selects_next_even_if_video_is_long(self):
        self.controller.records=[record(duration=1000),record('b',400,700)]
        self.assertEqual(self.controller.choose(399.9)[2],'a')
        self.assertEqual(self.controller.choose(400)[2],'b')
        self.assertIsNone(self.controller.choose(700)[1])

    def test_missing_media_retains_api_timer(self):
        with patch('helper.media_controller.cache_handler.get_media_path',return_value=None):
            result=self.controller.choose(250)
        self.assertEqual(result[1],400)
        self.assertIn('Waiting',result[3])

    def test_scroll_dwell_and_api_timer_are_separate(self):
        self.config['display']['Mode']='Scroll'
        self.controller.apply_config(self.config)
        self.assertEqual(self.controller.choose(200)[1],400)
        self.assertEqual(self.controller.scroll_until,210)
        self.assertEqual(self.controller.choose(211)[1],400)
        self.assertEqual(self.controller.scroll_until,221)

    def test_menu_preview_has_only_an_active_api_timer(self):
        self.config['display']['Mode']='Menu'
        self.controller.apply_config(self.config)
        self.controller.input(['ENTER'],200)
        self.assertEqual(self.controller.choose(250)[1],400)
        self.assertIsNotNone(self.controller.choose(400)[4])
        self.controller.input(['ENTER'],450)
        self.assertIsNone(self.controller.choose(450)[1])
        self.controller.input(['ESC'],450)
        self.assertIsNotNone(self.controller.choose(450)[4])

    def test_menu_shortened_or_removed_slot_closes_scheduled_preview(self):
        self.config['display']['Mode']='Menu'
        self.controller.apply_config(self.config)
        self.controller.input(['ENTER'],200)
        self.controller.records=[record(end=220)]
        self.assertIsNotNone(self.controller.choose(250)[4])
        self.assertIsNone(self.controller.preview)

    def test_screen_change_resets_preview_and_scroll(self):
        self.controller.preview={'url':'a'}
        changed=copy.deepcopy(self.config)
        changed['display']['screen_number']=8
        self.controller.apply_config(changed)
        self.assertIsNone(self.controller.preview)
        self.assertEqual(self.controller.scroll_until,0)

    def test_menu_start_button_updates_mode(self):
        self.config['display']['Mode']='Menu'
        self.controller.apply_config(self.config)
        self.controller.input(['CLICK','40','30'],200)
        self.controller.set_mode.assert_called_once_with('Time')
        self.assertEqual(self.controller.mode,'Time')

    def test_m_opens_menu_from_playback_and_persists_mode(self):
        for mode, key in (('Time', 'm'), ('Scroll', 'M')):
            with self.subTest(mode=mode):
                self.config['display']['Mode'] = mode
                self.controller.apply_config(self.config)
                self.controller.input([key], 200)
                self.controller.set_mode.assert_called_with('Menu')
                self.assertEqual(self.controller.mode, 'Menu')
                self.assertIsNotNone(self.controller.choose(200)[4])

    def test_m_returns_from_preview_and_escape_resumes_schedule(self):
        self.controller.input(['M'], 200)
        self.controller.input(['ENTER'], 200)
        self.assertIsNotNone(self.controller.preview)
        self.controller.input(['M'], 210)
        self.assertIsNone(self.controller.preview)
        self.assertEqual(self.controller.mode, 'Menu')
        self.controller.input(['ESC'], 220)
        self.controller.set_mode.assert_called_with('Time')
        self.assertEqual(self.controller.choose(220)[1], 400)

    def test_failed_m_mode_save_retains_playback(self):
        self.controller.set_mode.side_effect = OSError('disk unavailable')
        with self.assertLogs('helper.media_controller', level='ERROR'):
            self.controller.input(['M'], 200)
        self.assertEqual(self.controller.mode, 'Time')

    def test_failed_mode_save_keeps_menu_running(self):
        self.config['display']['Mode'] = 'Menu'
        self.controller.apply_config(self.config)
        self.controller.set_mode.side_effect = ValueError('invalid configuration')
        with self.assertLogs('helper.media_controller', level='ERROR'):
            self.controller.input(['CLICK', '40', '30'], 200)
        self.assertEqual(self.controller.mode, 'Menu')
        self.assertTrue(self.controller.running)

    def test_4k_menu_start_button_uses_scaled_hit_area(self):
        self.display.size=(3840,2160)
        self.config['display']['Mode']='Menu'
        self.controller.apply_config(self.config)
        self.controller.input(['CLICK','500','60'],200)
        self.controller.set_mode.assert_called_once_with('Time')


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_bounded_preparation_does_not_modify_originals(self):
        prepared=PreparedImages(self.root)
        originals=[]
        for i in range(6):
            path=self.root/f'original-{i}.jpg'
            Image.new('RGB',(800,600),(i,10,20)).save(path)
            originals.append((path,path.read_bytes()))
            output=prepared.prepare(path,(320,180))
            with Image.open(output) as image:
                self.assertEqual(image.size,(320,180))
        self.assertEqual(len(prepared.entries),3)
        self.assertEqual(len(list(self.root.glob('prepared-*.png'))),3)
        for path,data in originals:
            self.assertEqual(path.read_bytes(),data)

    def test_animation_and_video_are_never_expanded_to_frame_arrays(self):
        prepared=PreparedImages(self.root)
        for name in ('a.gif','b.mp4'):
            path=self.root/name
            self.assertEqual(prepared.prepare(path,(320,180)),path)
        self.assertEqual(len(prepared.entries),0)

    def test_transparent_posters_still_composite_on_black(self):
        source = self.root/'transparent.png'
        Image.new('RGBA', (20, 20), (200, 100, 50, 128)).save(source)
        original = source.read_bytes()
        output = PreparedImages(self.root).prepare(source, (40, 40))
        with Image.open(output) as image:
            self.assertEqual(image.mode, 'RGB')
            pixel = image.getpixel((20, 20))
            self.assertTrue(all(abs(a-b) <= 1 for a, b in zip(pixel, (100, 50, 25))))
        self.assertEqual(source.read_bytes(), original)

    def test_frame_hold_preserves_source_and_clears_footer_rgb(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = Image.new('RGB', (960, 540), 'red')
                hold = uncover_overlays(source, rotation)
                logical = hold.rotate(rotation, expand=True)
                self.assertEqual(logical.getpixel((logical.width//2, logical.height-1)), (0, 0, 0, 0))
                self.assertEqual(logical.getpixel((logical.width//2, 0)), (255, 0, 0, 255))
                self.assertEqual(source.getpixel((0, 0)), (255, 0, 0))

    def test_small_poster_fills_4k_without_cropping_edges(self):
        path=self.root/'small.png'
        source=Image.new('RGB',(100,60),'red')
        source.paste('green',(0,0,12,60))
        source.paste('blue',(88,0,100,60))
        source.save(path)
        prepared=PreparedImages(self.root)
        for size in ((3840,2160),(2160,3840)):
            with self.subTest(size=size), Image.open(prepared.prepare(path,size)) as image:
                self.assertEqual(image.size,size)
                self.assertEqual(image.getpixel((0,size[1]//2)),(0,128,0))
                self.assertEqual(image.getpixel((size[0]-1,size[1]//2)),(0,0,255))
                self.assertEqual(image.getpixel((size[0]//2,0)),(255,0,0))

    def test_4k_footer_stays_live_during_rotated_transitions(self):
        size=(3840,2160)
        for rotation in (0,90,180,270):
            hold=uncover_overlays(Image.new('RGB',size,'red'),rotation)
            logical=hold.rotate(rotation,expand=True)
            w,h=logical.size
            self.assertEqual(logical.getpixel((w//2,h-footer_height(size)+2)),(0,0,0,0))
            self.assertEqual(logical.getpixel((w//2,h-footer_height(size)-2)),(255,0,0,255))

    def test_media_viewport_reserves_footer_in_every_orientation(self):
        for size in ((1920,1080),(3840,2160)):
            for rotation,side in ((0,'bottom'),(90,'left'),(180,'top'),(270,'right')):
                with self.subTest(size=size,rotation=rotation):
                    w,h=logical_size(size,rotation)
                    self.assertEqual(media_size(size,rotation),(w,h-footer_height(size)))
                    margins=media_margins(size,rotation)
                    extent=size[0] if rotation%180 else size[1]
                    self.assertAlmostEqual(margins.pop(side)*extent,footer_height(size))
                    self.assertTrue(all(value==0 for value in margins.values()))
                    self.assertTrue(all(value==0 for value in media_margins(size,rotation,menu=True).values()))

    def test_menu_scales_geometry_and_preserves_footer_space_at_4k(self):
        for size in ((1920,1080),(1080,1920)):
            top,row,count=menu_geometry(size)
            top4,row4,count4=menu_geometry(tuple(v*2 for v in size))
            self.assertEqual((top4,row4,count4),(top*2,row*2,count))
            self.assertLessEqual(top4+row4*count4,size[1]*2-208)

    def test_menu_and_hold_rotation_match_input_coordinates(self):
        size=(960,540)
        for rotation in (0,90,180,270):
            logical=logical_size(size,rotation)
            menu=render_menu([],0,0,logical)
            self.assertEqual(menu.rotate(-rotation,expand=True).size,size)
            x,y={0:(30,30),90:(930,30),180:(930,510),270:(30,510)}[rotation]
            self.assertEqual(logical_point(x,y,size,rotation),(30,30))
            hold=uncover_overlays(Image.new('RGB',size,'red'),rotation)
            self.assertEqual(hold.getpixel((x,y)),(255,0,0,255))
            self.assertEqual(hold.getpixel((480,270)),(255,0,0,255))


class RefreshTests(unittest.TestCase):
    def test_refresh_is_serial_and_publishes_before_download_finishes(self):
        entered=threading.Event()
        release=threading.Event()
        calls=[]
        def refresh(token,hardware,publish):
            calls.append(hardware)
            publish([hardware],5)
            entered.set()
            release.wait(2)
            return [hardware],5
        worker=RefreshWorker(refresh)
        try:
            worker.request(('1','token','url',None))
            self.assertTrue(entered.wait(1))
            self.assertEqual(worker.read()[0][1],['1'])
            worker.request(('2','token','url',None))
            worker.request(('3','token','url',None))
            self.assertEqual(calls,['1'])
            release.set()
            deadline=time.monotonic()+2
            while worker.read()[0][0][0]!='3' and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(calls,['1','3'])
        finally:
            release.set()
            worker.close()
