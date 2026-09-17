import unittest
from unittest.mock import patch

from helper.mpv_player import video_output_options


class VideoOutputTests(unittest.TestCase):
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
