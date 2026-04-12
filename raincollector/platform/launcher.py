"""
Cross-platform browser profile shortcut / script launcher.

Windows: os.startfile() for .lnk shortcuts
Linux: subprocess.Popen(["bash", path]) for .sh scripts
"""
import os
import sys
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class Launcher(ABC):
    """Abstract shortcut launcher."""

    @abstractmethod
    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        """Launch a shortcut/script as a separate process. Returns Popen or None."""
        ...

    @abstractmethod
    def get_shortcut_glob(self) -> str:
        """Return a glob pattern for shortcuts (e.g. '*.lnk' or '*.sh')."""
        ...


class WindowsLauncher(Launcher):
    """Windows: os.startfile() for .lnk shortcuts."""

    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        os.startfile(str(path))  # type: ignore[attr-defined]
        # os.startfile does not return a process handle
        return None

    def get_shortcut_glob(self) -> str:
        return "*.lnk"


class LinuxLauncher(Launcher):
    """Linux: bash for .sh scripts."""

    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        # Ensure the script is executable
        if not os.access(str(path), os.X_OK):
            os.chmod(str(path), 0o755)
        return subprocess.Popen(
            ["bash", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detached process
        )

    def get_shortcut_glob(self) -> str:
        return "*.sh"


def get_launcher() -> Launcher:
    """Return the launcher appropriate for the current OS."""
    if sys.platform == "win32":
        return WindowsLauncher()
    else:
        return LinuxLauncher()
