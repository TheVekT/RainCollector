import asyncio
from raincollector.utils.plogging import Plogging
from raincollector.platform import PlatformWindow
import pyautogui


class pygetWindow:
    def __init__(self, window: PlatformWindow, logger: Plogging):
        self.rain_connected = False
        self.window: PlatformWindow = window
        self.plogging: Plogging = logger

    async def focus_window(self):
        """
        Focus the window (cross-platform via PlatformWindow).
        Uses .activate(), .restore() if necessary.
        Returns True if focus was set, False otherwise.
        """
        try:
            if not self.window:
                self.plogging.error("Window object is None. Cannot set focus.")
                return False
            try:
                if not self.window.is_active:
                    if self.window.is_minimized:
                        self.window.restore()
                        await asyncio.sleep(0.1)
                self.window.activate()
                await asyncio.sleep(0.1)

                # Check if the window is now active
                if self.window.is_active:
                    self.plogging.info("Window successfully activated and focused.")
                    await asyncio.sleep(0.2)
                    return True
                else:
                    self.plogging.warn("Window did not receive focus after activate(). Falling back.")
            except Exception as activate_error:
                self.plogging.warn(f"Error during activate(): {activate_error}")
        except Exception as e:
            self.plogging.error(f"Error setting focus: {e}")
        await asyncio.sleep(0.2)
        return False
    
    async def refresh_page(self):
        """
        Cross-platform page refresh using direct window messaging.
        """
        try:
            self.plogging.debug("Refreshing page via direct key input (F5)...")
            self.window.send_key("F5")
            await asyncio.sleep(3)
        except Exception as e:
            self.plogging.error(f"Failed to refresh page: {e}")
