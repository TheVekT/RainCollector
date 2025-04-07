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

    def __get__(self, instance, owner):
        if instance is None:
            return self
        # Возвращаем объект, который привязан к экземпляру
        return BoundManagedTask(self, instance)

class BoundManagedTask:
    def __init__(self, managed_task, instance):
        self.managed_task = managed_task
        self.instance = instance

    def start(self, *args, **kwargs):
        if self.managed_task._task and not self.managed_task._task.done():
            return
        self.managed_task._stop_event.clear()
        self.managed_task._paused.set()
        self.managed_task._task = asyncio.create_task(self._runner(*args, **kwargs))

    def stop(self):
        if self.managed_task._task:
            self.managed_task._stop_event.set()

    def pause(self):
        self.managed_task._paused.clear()

    def resume(self):
        self.managed_task._paused.set()

    def cancel(self):
        if self.managed_task._task:
            self.managed_task._task.cancel()
            self.managed_task._stop_event.set()
            self.managed_task._paused.set()

    async def _runner(self, *args, **kwargs):
        while not self.managed_task._stop_event.is_set():
            await self.managed_task._paused.wait()
            try:
                # Передаем экземпляр (self) в функцию
                await self.managed_task.func(self.instance, *args, **kwargs)
            except asyncio.CancelledError:
                break
            await asyncio.sleep(self.managed_task.interval)

def loop(seconds):
    def decorator(func):
        return ManagedTask(func, seconds)
    return decorator