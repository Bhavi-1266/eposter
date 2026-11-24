import queue
import threading
import time
import unittest

from helper.remote_input import RemoteInput
from radxa.radxa_receiver import Receiver
from radxa.radxa_receiver import StationFrames


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
        owner.events.put_nowait({'type': 'button', 'key': 'OK'})
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


class MockWrite:
    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
