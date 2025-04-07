import asyncio
from functools import wraps


class ManagedTask:
    def __init__(self, func, interval):
        self.func = func
        self.interval = interval
        self._task = None
        self._paused = asyncio.Event()
        self._paused.set()  # не на паузе
        self._stop_event = asyncio.Event()
        self._stop_event.clear()
        self._cancelled = False

    def start(self, *args, **kwargs):
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._paused.set()
        self._task = asyncio.create_task(self._runner(*args, **kwargs))


    def stop(self):
        if self._task:
            self._stop_event.set()


    def pause(self):
        self._paused.clear()


    def resume(self):
        self._paused.set()

    def cancel(self):
        if self._task:
            self._task.cancel()
            self._stop_event.set()
            self._paused.set()
            self._cancelled = True


    async def _runner(self, *args, **kwargs):
        while not self._stop_event.is_set():
            await self._paused.wait()
            try:
                await self.func(*args, **kwargs)
            except asyncio.CancelledError:
                break
            await asyncio.sleep(self.interval)

        
def loop(seconds):
    def decorator(func):
        task = ManagedTask(func, seconds)
        func.task = task  # добавим ссылку на объект ManagedTask
        return task
    return decorator