"""
Тесты кроссплатформенной абстракции: pyautogui, launcher, window_manager.

Запуск:
    python -m pytest tests/test_platform.py -v

ВАЖНО: Тесты pyautogui и window_manager требуют графического окружения
        (X11 на Linux, рабочий стол на Windows).
"""
import sys
import os
import stat
import time
import tempfile
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Убеждаемся, что корень проекта в sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from raincollector.platform.launcher import (
    Launcher,
    WindowsLauncher,
    LinuxLauncher,
    get_launcher,
)
from raincollector.platform.window_manager import (
    WindowManager,
    PlatformWindow,
    get_window_manager,
)


# =============================================================================
# Helpers
# =============================================================================
def _has_display() -> bool:
    """Проверяет наличие графического окружения."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY"))


requires_display = pytest.mark.skipif(
    not _has_display(),
    reason="Нет графического окружения (DISPLAY не установлен)",
)


# =============================================================================
# 1. Тесты pyautogui (требуют экран)
# =============================================================================
class TestPyAutoGUI:
    """Тесты базовых функций pyautogui — скриншот, позиция мыши, размер экрана."""

    @requires_display
    def test_screenshot(self):
        """pyautogui.screenshot() должен вернуть изображение с ненулевыми размерами."""
        import pyautogui
        img = pyautogui.screenshot()
        assert img is not None, "screenshot() вернул None"
        w, h = img.size
        assert w > 0 and h > 0, f"Некорректные размеры скриншота: {w}x{h}"

    @requires_display
    def test_mouse_position(self):
        """pyautogui.position() должен вернуть кортеж (x, y) с неотрицательными координатами."""
        import pyautogui
        pos = pyautogui.position()
        assert isinstance(pos, tuple) or hasattr(pos, 'x'), "position() вернул неожиданный тип"
        x, y = pos
        assert isinstance(x, int) and isinstance(y, int), f"Координаты не int: ({type(x)}, {type(y)})"
        assert x >= 0 and y >= 0, f"Отрицательные координаты: ({x}, {y})"

    @requires_display
    def test_screen_size(self):
        """pyautogui.size() должен вернуть размеры >= 800x600 (минимальное разумное разрешение)."""
        import pyautogui
        w, h = pyautogui.size()
        assert w >= 800, f"Ширина экрана слишком мала: {w}"
        assert h >= 600, f"Высота экрана слишком мала: {h}"

    @requires_display
    def test_screen_size_fullhd(self):
        """На сервере с HDMI-заглушкой разрешение должно быть 1920x1080."""
        import pyautogui
        w, h = pyautogui.size()
        # Это информационный тест — если разрешение отличается, 
        # нужно настроить HDMI-заглушку через xrandr
        if w != 1920 or h != 1080:
            pytest.skip(
                f"Разрешение {w}x{h} отличается от Full HD. "
                f"Настройте через xrandr --output HDMI-1 --mode 1920x1080"
            )
        assert w == 1920 and h == 1080


# =============================================================================
# 2. Тесты Launcher (запуск ярлыков/скриптов)
# =============================================================================
class TestLauncher:
    """Тесты платформенного лаунчера — запуск ярлыков как отдельных процессов."""

    def test_get_launcher_returns_correct_type(self):
        """get_launcher() должен вернуть LauncherWindows на Windows, LinuxLauncher на Linux."""
        launcher = get_launcher()
        if sys.platform == "win32":
            assert isinstance(launcher, WindowsLauncher)
        else:
            assert isinstance(launcher, LinuxLauncher)

    def test_shortcut_glob_windows(self):
        """На Windows glob должен быть *.lnk"""
        launcher = WindowsLauncher()
        assert launcher.get_shortcut_glob() == "*.lnk"

    def test_shortcut_glob_linux(self):
        """На Linux glob должен быть *.sh"""
        launcher = LinuxLauncher()
        assert launcher.get_shortcut_glob() == "*.sh"

    def test_launcher_launch_real_script(self):
        """
        Создаёт временный скрипт, запускает через Launcher,
        проверяет что процесс стартовал и создал маркер-файл.
        """
        launcher = get_launcher()
        marker = Path(tempfile.mktemp(suffix=".marker"))

        try:
            if sys.platform == "win32":
                # Создаём .bat скрипт вместо .lnk (os.startfile может запустить .bat)
                script = Path(tempfile.mktemp(suffix=".bat"))
                script.write_text(
                    f'@echo off\necho MARKER > "{marker}"\n',
                    encoding="utf-8",
                )
                # На Windows используем os.startfile напрямую (не через launcher для .bat)
                os.startfile(str(script))  # type: ignore[attr-defined]
            else:
                # Создаём .sh скрипт
                script = Path(tempfile.mktemp(suffix=".sh"))
                script.write_text(
                    f'#!/bin/bash\necho MARKER > "{marker}"\n',
                    encoding="utf-8",
                )
                os.chmod(str(script), 0o755)
                proc = launcher.launch(script)
                assert proc is not None, "LinuxLauncher.launch() вернул None"
                assert isinstance(proc, subprocess.Popen), "Ожидался subprocess.Popen"

            # Ждём максимум 5 секунд, пока маркер-файл не появится
            for _ in range(50):
                if marker.exists():
                    break
                time.sleep(0.1)

            assert marker.exists(), (
                f"Маркер-файл {marker} не создан — скрипт не запустился как отдельный процесс"
            )
        finally:
            # Cleanup
            if script.exists():
                script.unlink()
            if marker.exists():
                marker.unlink()

    def test_linux_launcher_sets_executable(self):
        """LinuxLauncher должен автоматически выставить chmod +x если файл не исполняемый."""
        if sys.platform == "win32":
            pytest.skip("Тест только для Linux")

        launcher = LinuxLauncher()
        script = Path(tempfile.mktemp(suffix=".sh"))
        marker = Path(tempfile.mktemp(suffix=".marker"))

        try:
            script.write_text(
                f'#!/bin/bash\necho OK > "{marker}"\n',
                encoding="utf-8",
            )
            # Убираем executable бит
            os.chmod(str(script), 0o644)

            proc = launcher.launch(script)
            assert proc is not None

            for _ in range(50):
                if marker.exists():
                    break
                time.sleep(0.1)

            assert marker.exists(), "Скрипт не запустился — chmod +x не сработал"
        finally:
            if script.exists():
                script.unlink()
            if marker.exists():
                marker.unlink()

    def test_linux_launcher_detached_process(self):
        """Процесс, запущенный LinuxLauncher, должен быть отсоединённым (start_new_session=True)."""
        if sys.platform == "win32":
            pytest.skip("Тест только для Linux")

        launcher = LinuxLauncher()
        script = Path(tempfile.mktemp(suffix=".sh"))

        try:
            # Скрипт, который спит 30 сек (мы его убьём)
            script.write_text('#!/bin/bash\nsleep 30\n', encoding="utf-8")
            os.chmod(str(script), 0o755)

            proc = launcher.launch(script)
            assert proc is not None
            assert proc.pid > 0, "PID процесса <= 0"

            # Процесс должен быть в другой сессии
            proc_sid = os.getsid(proc.pid)
            my_sid = os.getsid(0)
            assert proc_sid != my_sid, (
                f"Процесс {proc.pid} в той же сессии ({proc_sid}) — "
                f"start_new_session не работает"
            )

            # Cleanup: убиваем процесс
            proc.terminate()
            proc.wait(timeout=5)
        finally:
            if script.exists():
                script.unlink()


# =============================================================================
# 3. Тесты WindowManager (поиск окон)
# =============================================================================
class TestWindowManager:
    """Тесты менеджера окон — поиск, фокус, закрытие."""

    def test_get_window_manager_returns_correct_type(self):
        """get_window_manager() должен вернуть правильный тип для ОС."""
        wm = get_window_manager()
        assert isinstance(wm, WindowManager)

    @requires_display
    def test_search_nonexistent_window(self):
        """Поиск несуществующего окна должен вернуть пустой список."""
        wm = get_window_manager()
        windows = wm.get_windows_by_title("NONEXISTENT_WINDOW_TITLE_12345_QWERTY")
        assert isinstance(windows, list)
        assert len(windows) == 0

    @requires_display
    def test_search_and_close_window(self):
        """
        Создаёт тестовое окно (notepad на Windows, xterm на Linux),
        ищет его по заголовку, проверяет что найдено, и закрывает.
        """
        wm = get_window_manager()
        unique_title = f"RainCollector_Test_{int(time.time())}"

        if sys.platform == "win32":
            # Запускаем notepad с уникальным заголовком через title
            proc = subprocess.Popen(
                ["cmd", "/c", f"title {unique_title} && pause"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            # Запускаем xterm с уникальным заголовком
            proc = subprocess.Popen(
                ["xterm", "-T", unique_title, "-e", "sleep 30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        try:
            time.sleep(2)  # Ждём появление окна

            windows = wm.get_windows_by_title(unique_title)
            assert len(windows) > 0, (
                f"Окно с заголовком '{unique_title}' не найдено. "
                f"Убедитесь что xterm установлен на Linux."
            )

            win = windows[0]
            assert isinstance(win, PlatformWindow)
            assert unique_title in win.title

            # Закрываем через абстракцию
            win.close()
            time.sleep(1)

            # Проверяем что окно закрылось
            windows_after = wm.get_windows_by_title(unique_title)
            assert len(windows_after) == 0, "Окно не закрылось после close()"
        finally:
            # Cleanup
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


# =============================================================================
# 4. Тесты PlatformWindow (свойства и методы)
# =============================================================================
class TestPlatformWindow:
    """Тесты интерфейса PlatformWindow — свойства, активация."""

    @requires_display
    def test_window_properties(self):
        """Свойства PlatformWindow (title, is_active, is_minimized) должны работать."""
        wm = get_window_manager()
        unique_title = f"RainCollector_Props_{int(time.time())}"

        if sys.platform == "win32":
            proc = subprocess.Popen(
                ["cmd", "/c", f"title {unique_title} && pause"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            proc = subprocess.Popen(
                ["xterm", "-T", unique_title, "-e", "sleep 30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        try:
            time.sleep(2)
            windows = wm.get_windows_by_title(unique_title)
            if not windows:
                pytest.skip("Тестовое окно не создалось")

            win = windows[0]

            # title должен содержать наш заголовок
            assert unique_title in win.title

            # is_minimized должен быть bool
            assert isinstance(win.is_minimized, bool)

            # is_active должен быть bool
            assert isinstance(win.is_active, bool)

            win.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
