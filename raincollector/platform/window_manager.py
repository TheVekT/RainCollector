"""
Кроссплатформенное управление окнами.

Windows: pygetwindow (Win32 API)
Linux: xdotool через subprocess
"""
import sys
import subprocess
import asyncio
from abc import ABC, abstractmethod
from typing import Optional


class PlatformWindow(ABC):
    """Абстрактное окно — единый интерфейс для Win32Window и xdotool."""

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    @abstractmethod
    def is_active(self) -> bool: ...

    @property
    @abstractmethod
    def is_minimized(self) -> bool: ...

    @abstractmethod
    def activate(self) -> None: ...

    @abstractmethod
    def restore(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class WindowManager(ABC):
    """Абстрактный менеджер окон."""

    @abstractmethod
    def get_windows_by_title(self, title: str) -> list[PlatformWindow]: ...


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import pygetwindow as gw  # type: ignore[import-untyped]

    class _Win32PlatformWindow(PlatformWindow):
        def __init__(self, win: gw.Win32Window):
            self._win: gw.Win32Window = win

        @property
        def title(self) -> str:
            return self._win.title

        @property
        def is_active(self) -> bool:
            return self._win.isActive

        @property
        def is_minimized(self) -> bool:
            return self._win.isMinimized

        def activate(self) -> None:
            self._win.activate()

        def restore(self) -> None:
            self._win.restore()

        def close(self) -> None:
            self._win.close()

    class Win32WindowManager(WindowManager):
        def get_windows_by_title(self, title: str) -> list[PlatformWindow]:
            raw = gw.getWindowsWithTitle(title)
            return [_Win32PlatformWindow(w) for w in raw]

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
else:

    class _XdotoolPlatformWindow(PlatformWindow):
        """Обёртка над xdotool window-id."""

        def __init__(self, window_id: str):
            self._wid = window_id
            self._title_cache: Optional[str] = None

        # --- helpers ---
        def _run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["xdotool", *args],
                capture_output=True, text=True, check=check,
            )

        def _xprop(self, prop: str) -> str:
            """Читает свойство окна через xprop."""
            result = subprocess.run(
                ["xprop", "-id", self._wid, prop],
                capture_output=True, text=True,
            )
            return result.stdout.strip()

        # --- interface ---
        @property
        def title(self) -> str:
            if self._title_cache is None:
                result = self._run("getwindowname", self._wid)
                self._title_cache = result.stdout.strip() or ""
            return self._title_cache

        @property
        def is_active(self) -> bool:
            result = self._run("getactivewindow")
            active_wid = result.stdout.strip()
            return active_wid == self._wid

        @property
        def is_minimized(self) -> bool:
            out = self._xprop("WM_STATE")
            # WM_STATE содержит "Iconic" для свёрнутых окон
            return "Iconic" in out or "iconic" in out.lower()

        def activate(self) -> None:
            self._run("windowactivate", "--sync", self._wid)

        def restore(self) -> None:
            # Если окно свёрнуто — активируем (xdotool сам разворачивает)
            self._run("windowactivate", "--sync", self._wid)

        def close(self) -> None:
            self._run("windowclose", self._wid)

    class LinuxWindowManager(WindowManager):
        def get_windows_by_title(self, title: str) -> list[PlatformWindow]:
            result = subprocess.run(
                ["xdotool", "search", "--name", title],
                capture_output=True, text=True,
            )
            if not result.stdout.strip():
                return []
            wids = result.stdout.strip().split("\n")
            return [_XdotoolPlatformWindow(wid) for wid in wids if wid]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_window_manager() -> WindowManager:
    """Возвращает менеджер окон, подходящий для текущей ОС."""
    if sys.platform == "win32":
        return Win32WindowManager()
    else:
        return LinuxWindowManager()
