"""
Кроссплатформенный запуск ярлыков / скриптов браузерных профилей.

Windows: os.startfile() для .lnk
Linux: subprocess.Popen(["bash", path]) для .sh
"""
import os
import sys
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class Launcher(ABC):
    """Абстрактный запускатель ярлыков."""

    @abstractmethod
    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        """Запускает ярлык/скрипт как отдельный процесс. Возвращает Popen или None."""
        ...

    @abstractmethod
    def get_shortcut_glob(self) -> str:
        """Возвращает glob-паттерн для ярлыков (например '*.lnk' или '*.sh')."""
        ...


class WindowsLauncher(Launcher):
    """Windows: os.startfile() для .lnk ярлыков."""

    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        os.startfile(str(path))  # type: ignore[attr-defined]
        # os.startfile не возвращает процесс, возвращаем None
        return None

    def get_shortcut_glob(self) -> str:
        return "*.lnk"


class LinuxLauncher(Launcher):
    """Linux: bash для .sh скриптов."""

    def launch(self, path: Path) -> Optional[subprocess.Popen]:
        # Убедимся что скрипт исполняемый
        if not os.access(str(path), os.X_OK):
            os.chmod(str(path), 0o755)
        return subprocess.Popen(
            ["bash", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # отсоединяемый процесс
        )

    def get_shortcut_glob(self) -> str:
        return "*.sh"


def get_launcher() -> Launcher:
    """Возвращает лаунчер, подходящий для текущей ОС."""
    if sys.platform == "win32":
        return WindowsLauncher()
    else:
        return LinuxLauncher()
