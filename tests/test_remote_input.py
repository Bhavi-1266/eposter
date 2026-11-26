import json
import os
from pathlib import Path
import pty
import queue
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from helper.remote_input import RemoteInput
from radxa.radxa_receiver import Receiver
from radxa.radxa_receiver import StationFrames
from radxa.uart_protocol import JsonInputReceiver, encode_message


def input_without_thread(size=1):
    owner = RemoteInput.__new__(RemoteInput)
    owner.events = queue.Queue(maxsize=size)
    owner.motion_lock = threading.Lock()
    owner.motion = [0, 0]
    owner.motion_at = 0.0
    owner.motion_limit = 20
    owner.motion_max_age = 0.35
    return owner


class RemoteQueueTests(unittest.TestCase):
    def test_uart_io_error_reconnects_instead_of_killing_worker(self):
        import termios
        owner = input_without_thread()
        owner.stop = Mock()
        owner.stop.is_set.side_effect = [False, False, True]
        owner.reconnect_delay = 2
        owner._run_connection = Mock(side_effect=termios.error(5, 'Input/output error'))
        with self.assertLogs('helper.remote_input', level='WARNING'):
            owner._run()
        owner.stop.wait.assert_called_once_with(2)

    def test_ack_is_withheld_until_bounded_queue_accepts_button(self):
        owner = input_without_thread()
        receiver = Receiver(owner._accept)
        first = b'EV 00000001 00000001 1 4 0 3000'
        second = b'EV 00000001 00000002 1 1 0 3000'
        self.assertEqual(receiver.process(first), b'ACK 00000001 00000001\n')
        with self.assertRaises(queue.Full):
            receiver.process(second)
        self.assertEqual([event['key'] for event in owner.read()], ['OK'])
        self.assertEqual(receiver.process(second), b'ACK 00000001 00000002\n')
        self.assertEqual([event['key'] for event in owner.read()], ['UP'])
        self.assertEqual(receiver.process(second), b'ACK 00000001 00000002\n')
        self.assertEqual(list(owner.read()), [])

    def test_motion_is_coalesced_bounded_and_never_acked(self):
        owner = input_without_thread()
        receiver = Receiver(owner._accept)
        for sequence in (1, 2):
            line = f'EV 00000001 {sequence:08x} 2 15 -15 3000'.encode()
            self.assertIsNone(receiver.process(line))
        self.assertEqual(list(owner.read()), [{'type': 'motion', 'dx': 20, 'dy': -20}])

    def test_stale_motion_is_discarded(self):
        owner = input_without_thread()
        owner._accept({'type': 'motion', 'dx': 5, 'dy': 7})
        owner.motion_at = time.monotonic() - 1
        self.assertEqual(list(owner.read()), [])

    def test_full_button_queue_does_not_drop_later_motion_frame(self):
        owner = input_without_thread()
        owner._accept({'type': 'button', 'key': 'OK'})
        frames = StationFrames(Receiver(owner._accept))
        chunk = (b'EV 00000001 00000001 1 1 0 3000\n'
                 b'EV 00000001 00000002 2 7 -9 3000\n')
        owner._feed_chunk(frames, chunk, MockWrite())
        events = list(owner.read())
        self.assertEqual(events[0]['key'], 'OK')
        self.assertEqual(events[1], {'type': 'motion', 'dx': 7, 'dy': -9})

    def test_probes_do_not_consume_button_capacity(self):
        owner = input_without_thread()
        receiver = Receiver(owner._accept)
        self.assertEqual(receiver.process(b'EV 00000001 00000001 3 0 0 3000'),
                         b'ACK 00000001 00000001\n')
        self.assertEqual(list(owner.read()), [])
        self.assertEqual(receiver.process(b'EV 00000001 00000002 1 4 0 3000'),
                         b'ACK 00000001 00000002\n')

    def test_json_buttons_retry_once_and_aim_gates_cursor(self):
        owner = input_without_thread()
        frames = StationFrames(Receiver(owner._accept), json_input=JsonInputReceiver(owner._accept_json))
        write = MockWrite()
        left = encode_message({'v': 1, 'type': 'input', 'id': '8f2a1c90:00000042',
                               'data': [0, 0, 0, 1, 0, 0, 0, 0, 0, 12, 23]})
        owner._feed_chunk(frames, left[:30], write)
        self.assertEqual(write.messages, [])
        owner._feed_chunk(frames, left[30:] + left, write)
        ack = {'v': 1, 'type': 'ack', 'id': '8f2a1c90:00000042'}
        self.assertEqual([json.loads(message) for message in write.messages], [ack, ack])
        self.assertEqual(list(owner.read()), [{'type': 'button', 'key': 'LEFT'}])

    def test_json_full_queue_rejects_entire_report_but_motion_keeps_streaming(self):
        owner = input_without_thread()
        frames = StationFrames(Receiver(owner._accept), json_input=JsonInputReceiver(owner._accept_json))
        write = MockWrite()
        owner._accept({'type': 'button', 'key': 'HOME'})
        buttons = {'v': 1, 'type': 'input', 'id': 'buttons', 'data': [1, 1, 0, 0, 0, 1, 0, 0, 0, 6, -2]}
        motion = {'v': 1, 'type': 'input', 'id': 'aim', 'data': [1, 0, 0, 0, 0, 0, 0, 0, 0, 3, -4]}
        with self.assertLogs('helper.remote_input', level='WARNING'):
            owner._feed_chunk(frames, encode_message(buttons) + encode_message(motion) * 2, write)
        self.assertEqual([json.loads(ack)['id'] for ack in write.messages], ['aim', 'aim'])
        self.assertEqual(list(owner.read()), [{'type': 'button', 'key': 'HOME'},
                                             {'type': 'motion', 'dx': 3, 'dy': -4}])
        owner._feed_chunk(frames, encode_message(buttons) * 2, write)
        self.assertEqual([json.loads(ack)['id'] for ack in write.messages[-2:]], ['buttons', 'buttons'])
        self.assertEqual(list(owner.read()), [{'type': 'button', 'key': 'UP'},
                                             {'type': 'button', 'key': 'OK'},
                                             {'type': 'motion', 'dx': 6, 'dy': -2}])

    def test_json_bad_frames_are_skipped_and_parser_resynchronizes(self):
        owner = input_without_thread()
        frames = StationFrames(Receiver(owner._accept), json_input=JsonInputReceiver(owner._accept_json))
        write = MockWrite()
        invalid = {'v': 1, 'type': 'input', 'id': 'bad', 'data': [False] + [0] * 10}
        valid = {'v': 1, 'type': 'input', 'id': 'good', 'data': [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]}
        owner._feed_chunk(frames, b'{' + b'x' * 1600, write)
        owner._feed_chunk(frames, b'\n' + encode_message(invalid) + encode_message(valid), write)
        self.assertEqual([json.loads(ack)['id'] for ack in write.messages], ['good'])
        self.assertEqual(list(owner.read()), [{'type': 'button', 'key': 'OK'}])


class RemoteUartTests(unittest.TestCase):
    def test_config_replies_and_inputs_share_the_live_uart_owner(self):
        script = Path(__file__).resolve().parents[1] / 'radxa' / 'remote'
        with tempfile.TemporaryDirectory() as runtime, patch.dict(os.environ, {'XDG_RUNTIME_DIR': runtime}):
            master, slave = pty.openpty()
            owner = RemoteInput(os.ttyname(slave), reconnect_delay=.1)
            try:
                deadline = time.monotonic() + 5
                while not (Path(runtime) / 'radxa-remote' / 'control.sock').exists():
                    self.assertLess(time.monotonic(), deadline, 'UART owner did not start')
                    time.sleep(.02)

                def read_json():
                    line = bytearray()
                    end = time.monotonic() + 5
                    while not line.endswith(b'\n'):
                        self.assertTrue(select.select([master], [], [], max(0, end - time.monotonic()))[0],
                                        'UART message timed out')
                        line.extend(os.read(master, 1))
                    return json.loads(line)

                def run_request(args, target, settings, result_data, expect_ok):
                    client = subprocess.Popen([sys.executable, str(script), 'set-config', target, *args],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        request = read_json()
                        self.assertEqual(request, {'v': 1, 'type': 'config', 'id': request['id'],
                                                   'op': 'set', 'target': target, 'data': settings})
                        result = {'v': 1, 'type': 'config_result', 'id': request['id'],
                                  'status': 'ok', 'data': result_data}
                        wrong = dict(result, id='unrelated')
                        press = {'v': 1, 'type': 'input', 'id': 'eptest:press',
                                 'data': [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]}
                        os.write(master, encode_message({'v': 1, 'type': 'ack', 'id': request['id']})
                                 + encode_message(wrong) + encode_message(press))
                        self.assertEqual(read_json(), {'v': 1, 'type': 'ack', 'id': press['id']})
                        self.assertIsNone(client.poll(), 'Unexpected confirmation before matching config_result')
                        os.write(master, encode_message(result))
                        stdout, stderr = client.communicate(timeout=5)
                        if expect_ok:
                            self.assertEqual(client.returncode, 0, stderr)
                            self.assertEqual(json.loads(stdout), result)
                        else:
                            self.assertNotEqual(client.returncode, 0)
                            self.assertIn(b'INVALID CONFIG_RESULT', stderr)
                    finally:
                        if client.poll() is None:
                            client.kill()
                        client.communicate(timeout=5)

                run_request(['--device-id', 'remote-012', '--channel', '6'], 'remote-001',
                            {'device_id': 'remote-012', 'channel': 6}, {'device_id': 'remote-012', 'channel': 6}, True)
                run_request(['--channel', '7'], 'remote-012', {'channel': 7},
                            {'device_id': 'remote-012', 'channel': 6}, False)
                self.assertEqual(list(owner.read()), [{'type': 'button', 'key': 'OK'}])
            finally:
                owner.close()
                os.close(master)
                os.close(slave)


class MockWrite:
    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
