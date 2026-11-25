"""Bounded manual commands with a stop attempted after every movement."""
import asyncio
import math

DIRECTIONS = ("forward", "backward", "turn_left", "turn_right", "right_forward", "left_forward")


class ManualControl:
    def __init__(self, write):
        self.write = write
        self.lock = asyncio.Lock()
        self.stopped = asyncio.Event()

    async def stop(self):
        self.stopped.set()
        await self.write({"12": "stop"})

    async def step(self, direction, duration=.3):
        if direction not in DIRECTIONS or isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not .1 <= duration <= 1:
            raise ValueError("Choose a direction and duration between 0.1 and 1 seconds")
        if self.lock.locked():
            raise ValueError("A manual movement is already running")
        async with self.lock:
            self.stopped.clear()
            try:
                await self.write({"4": "manual"})
                # A simultaneous stop during entry must prevent the movement.
                if self.stopped.is_set():
                    return
                await self.write({"12": direction})
                try:
                    await asyncio.wait_for(self.stopped.wait(), timeout=duration)
                except TimeoutError:
                    pass
            finally:
                await self.stop()
