"""
Tests for the cross-platform abstraction: pyautogui, launcher, window_manager.

Usage:
    python -m pytest tests/test_platform.py -v

NOTE: pyautogui and window_manager tests require a graphical environment
      (X11 on Linux, desktop on Windows).
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

# Ensure project root is in sys.path
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
    """Check if a graphical environment is available."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY"))


requires_display = pytest.mark.skipif(
    not _has_display(),
    reason="No graphical environment (DISPLAY not set)",
)


# =============================================================================
# 1. PyAutoGUI tests (require a display)
# =============================================================================
class TestPyAutoGUI:
    """Tests for basic pyautogui functions — screenshot, mouse position, screen size."""

    @requires_display
    def test_screenshot(self):
        """pyautogui.screenshot() should return an image with non-zero dimensions."""
        import pyautogui
        img = pyautogui.screenshot()
        assert img is not None, "screenshot() returned None"
        w, h = img.size
        assert w > 0 and h > 0, f"Invalid screenshot dimensions: {w}x{h}"

    @requires_display
    def test_mouse_position(self):
        """pyautogui.position() should return a (x, y) tuple with non-negative coords."""
        import pyautogui
        pos = pyautogui.position()
        assert isinstance(pos, tuple) or hasattr(pos, 'x'), "position() returned unexpected type"
        x, y = pos
        assert isinstance(x, int) and isinstance(y, int), f"Coords are not int: ({type(x)}, {type(y)})"
        assert x >= 0 and y >= 0, f"Negative coords: ({x}, {y})"

    @requires_display
    def test_screen_size(self):
        """pyautogui.size() should return dimensions >= 800x600 (minimum reasonable resolution)."""
        import pyautogui
        w, h = pyautogui.size()
        assert w >= 800, f"Screen width too small: {w}"
        assert h >= 600, f"Screen height too small: {h}"

    @requires_display
    def test_screen_size_fullhd(self):
        """On a server with an HDMI dummy plug, resolution should be 1920x1080."""
        import pyautogui
        w, h = pyautogui.size()
        # Informational test — if resolution differs, configure HDMI dummy via xrandr
        if w != 1920 or h != 1080:
            pytest.skip(
                f"Resolution {w}x{h} differs from Full HD. "
                f"Configure via xrandr --output HDMI-1 --mode 1920x1080"
            )
        assert w == 1920 and h == 1080


# =============================================================================
# 2. Launcher tests (shortcut/script launching)
# =============================================================================
class TestLauncher:
    """Tests for the platform launcher — launching shortcuts as separate processes."""

    def test_get_launcher_returns_correct_type(self):
        """get_launcher() should return WindowsLauncher on Windows, LinuxLauncher on Linux."""
        launcher = get_launcher()
        if sys.platform == "win32":
            assert isinstance(launcher, WindowsLauncher)
        else:
            assert isinstance(launcher, LinuxLauncher)

    def test_shortcut_glob_windows(self):
        """On Windows, glob should be *.lnk"""
        launcher = WindowsLauncher()
        assert launcher.get_shortcut_glob() == "*.lnk"

    def test_shortcut_glob_linux(self):
        """On Linux, glob should be *.sh"""
        launcher = LinuxLauncher()
        assert launcher.get_shortcut_glob() == "*.sh"

    def test_launcher_launch_real_script(self):
        """
        Create a temporary script, launch it via Launcher,
        verify the process started and created a marker file.
        """
        launcher = get_launcher()
        marker = Path(tempfile.mktemp(suffix=".marker"))

        try:
            if sys.platform == "win32":
                # Create a .bat script (os.startfile can launch .bat)
                script = Path(tempfile.mktemp(suffix=".bat"))
                script.write_text(
                    f'@echo off\necho MARKER > "{marker}"\n',
                    encoding="utf-8",
                )
                # On Windows use os.startfile directly (not launcher for .bat)
                os.startfile(str(script))  # type: ignore[attr-defined]
            else:
                # Create a .sh script
                script = Path(tempfile.mktemp(suffix=".sh"))
                script.write_text(
                    f'#!/bin/bash\necho MARKER > "{marker}"\n',
                    encoding="utf-8",
                )
                os.chmod(str(script), 0o755)
                proc = launcher.launch(script)
                assert proc is not None, "LinuxLauncher.launch() returned None"
                assert isinstance(proc, subprocess.Popen), "Expected subprocess.Popen"

            # Wait up to 5 seconds for the marker file to appear
            for _ in range(50):
                if marker.exists():
                    break
                time.sleep(0.1)

            assert marker.exists(), (
                f"Marker file {marker} not created — script did not run as a separate process"
            )
        finally:
            # Cleanup
            if script.exists():
                script.unlink()
            if marker.exists():
                marker.unlink()

    def test_linux_launcher_sets_executable(self):
        """LinuxLauncher should automatically chmod +x if the file is not executable."""
        if sys.platform == "win32":
            pytest.skip("Linux-only test")

        launcher = LinuxLauncher()
        script = Path(tempfile.mktemp(suffix=".sh"))
        marker = Path(tempfile.mktemp(suffix=".marker"))

        try:
            script.write_text(
                f'#!/bin/bash\necho OK > "{marker}"\n',
                encoding="utf-8",
            )
            # Remove executable bit
            os.chmod(str(script), 0o644)

            proc = launcher.launch(script)
            assert proc is not None

            for _ in range(50):
                if marker.exists():
                    break
                time.sleep(0.1)

            assert marker.exists(), "Script did not run — chmod +x did not work"
        finally:
            if script.exists():
                script.unlink()
            if marker.exists():
                marker.unlink()

    def test_linux_launcher_detached_process(self):
        """Process launched by LinuxLauncher should be detached (start_new_session=True)."""
        if sys.platform == "win32":
            pytest.skip("Linux-only test")

        launcher = LinuxLauncher()
        script = Path(tempfile.mktemp(suffix=".sh"))

        try:
            # Script that sleeps 30 sec (we will kill it)
            script.write_text('#!/bin/bash\nsleep 30\n', encoding="utf-8")
            os.chmod(str(script), 0o755)

            proc = launcher.launch(script)
            assert proc is not None
            assert proc.pid > 0, "Process PID <= 0"

            # Process should be in a different session
            proc_sid = os.getsid(proc.pid)
            my_sid = os.getsid(0)
            assert proc_sid != my_sid, (
                f"Process {proc.pid} is in the same session ({proc_sid}) — "
                f"start_new_session is not working"
            )

            # Cleanup: kill the process
            proc.terminate()
            proc.wait(timeout=5)
        finally:
            if script.exists():
                script.unlink()


# =============================================================================
# 3. WindowManager tests (window search)
# =============================================================================
class TestWindowManager:
    """Tests for window manager — search, focus, close."""

    def test_get_window_manager_returns_correct_type(self):
        """get_window_manager() should return the correct type for the OS."""
        wm = get_window_manager()
        assert isinstance(wm, WindowManager)

    @requires_display
    def test_search_nonexistent_window(self):
        """Searching for a non-existent window should return an empty list."""
        wm = get_window_manager()
        windows = wm.get_windows_by_title("NONEXISTENT_WINDOW_TITLE_12345_QWERTY")
        assert isinstance(windows, list)
        assert len(windows) == 0

    @requires_display
    def test_search_and_close_window(self):
        """
        Create a test window (notepad on Windows, xterm on Linux),
        search for it by title, verify it's found, and close it.
        """
        wm = get_window_manager()
        unique_title = f"RainCollector_Test_{int(time.time())}"

        if sys.platform == "win32":
            # Launch a cmd window with a unique title
            proc = subprocess.Popen(
                ["cmd", "/c", f"title {unique_title} && pause"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            # Launch xterm with a unique title
            proc = subprocess.Popen(
                ["xterm", "-T", unique_title, "-e", "sleep 30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        try:
            time.sleep(2)  # Wait for the window to appear

            windows = wm.get_windows_by_title(unique_title)
            assert len(windows) > 0, (
                f"Window with title '{unique_title}' not found. "
                f"Make sure xterm is installed on Linux."
            )

            win = windows[0]
            assert isinstance(win, PlatformWindow)
            assert unique_title in win.title

            # Close via the abstraction
            win.close()
            time.sleep(1)

            # Verify the window is closed
            windows_after = wm.get_windows_by_title(unique_title)
            assert len(windows_after) == 0, "Window did not close after close()"
        finally:
            # Cleanup
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


# =============================================================================
# 4. PlatformWindow tests (properties and methods)
# =============================================================================
class TestPlatformWindow:
    """Tests for PlatformWindow interface — properties, activation."""

    @requires_display
    def test_window_properties(self):
        """PlatformWindow properties (title, is_active, is_minimized) should work."""
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
                pytest.skip("Test window was not created")

            win = windows[0]

            # title should contain our title string
            assert unique_title in win.title

            # is_minimized should be bool
            assert isinstance(win.is_minimized, bool)

            # is_active should be bool
            assert isinstance(win.is_active, bool)

            win.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
