import unittest
from unittest.mock import patch

from helper.mpv_player import playback_settings, video_output_options


class VideoOutputTests(unittest.TestCase):
    def test_radxa_profile_uses_tested_render_settings(self):
        options = video_output_options(profile='radxa-zero3')
        for option in ('--vo=gpu', '--profile=fast', '--swapchain-depth=8',
                       '--opengl-swapinterval=0', '--x11-bypass-compositor=yes'):
            self.assertIn(option, options)

    def test_radxa_decoder_default_preserves_explicit_overrides(self):
        self.assertEqual(playback_settings({'video_profile': 'radxa-zero3'})['hwdec'], 'rkmpp')
        for hwdec in ('no', 'rkmpp-copy'):
            self.assertEqual(playback_settings({'video_profile': 'radxa-zero3', 'video_hwdec': hwdec})['hwdec'], hwdec)
        self.assertEqual(playback_settings({}), {'hwdec': 'auto', 'profile': 'default', 'audio': True})

    def test_audio_off_and_invalid_settings(self):
        self.assertFalse(playback_settings({'video_audio': False})['audio'])
        for settings in ({'video_audio': 'false'}, {'video_profile': 'unknown'}):
            with self.assertRaises(ValueError):
                playback_settings(settings)

    def test_arm_boards_avoid_libplacebo_renderer(self):
        for machine in ('aarch64', 'arm64', 'armv7l'):
            with self.subTest(machine=machine), patch('helper.mpv_player.platform.machine', return_value=machine):
                self.assertEqual(video_output_options(), ['--vo=gpu', '--gpu-api=opengl'])

    def test_desktop_retains_validated_renderer(self):
        with patch('helper.mpv_player.platform.machine', return_value='x86_64'):
            self.assertIn('--vo=gpu-next,gpu', video_output_options())

    def test_software_visual_checks_retain_validated_renderer(self):
        with patch('helper.mpv_player.platform.machine', return_value='aarch64'):
            options = video_output_options(software_rendering=True)
            self.assertIn('--vo=gpu-next,gpu', options)
            self.assertIn('--gpu-sw=yes', options)

    def test_headless_does_not_initialize_graphics(self):
        self.assertEqual(video_output_options(headless=True),
                         ['--vo=null', '--ao=null', '--force-window=no'])
