"""Reusable in-memory cooldown helper."""
import time

class Cooldown:
    def __init__(self):
        self._until = {}
    def ready(self, key):
        return time.monotonic() >= self._until.get(str(key), 0)
    def remaining(self, key):
        return max(0.0, self._until.get(str(key), 0) - time.monotonic())
    def set(self, key, seconds):
        self._until[str(key)] = time.monotonic() + float(seconds)
