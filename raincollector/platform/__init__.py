"""
Кроссплатформенный слой абстракции.

Использование:
    from raincollector.platform import get_window_manager, get_launcher

    wm = get_window_manager()
    windows = wm.get_windows_by_title("Chrome")

    launcher = get_launcher()
    launcher.launch(Path("accounts/profile.sh"))
"""
from raincollector.platform.window_manager import (
    PlatformWindow,
    WindowManager,
    get_window_manager,
)
from raincollector.platform.launcher import (
    Launcher,
    get_launcher,
)

__all__ = [
    "PlatformWindow",
    "WindowManager",
    "get_window_manager",
    "Launcher",
    "get_launcher",
]
