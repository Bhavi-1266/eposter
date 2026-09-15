"""API deadline countdown; media start, buffering and looping never reset it."""
import math
import time


def format_remaining(seconds):
    seconds = max(0, math.ceil(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class PlaybackTimer:
    def __init__(self, deadline):
        self.deadline = float(deadline)

    @property
    def remaining(self):
        return max(0, self.deadline - time.time())

    @property
    def text(self):
        return format_remaining(self.remaining)
