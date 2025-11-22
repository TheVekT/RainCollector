import asyncio
from raincollector.utils.plogging import Plogging
import pygetwindow as gw
import pyautogui

class pygetWindow:
    def __init__(self, window: gw.Win32Window, logger: Plogging):
        self.rain_connected = False
        self.window: gw.Win32Window = window
        self.plogging: Plogging = logger

    async def focus_window(self):
        """
        Ставит фокус на окно (pygetwindow.Win32Window).
        Использует .activate(), .bringToFront() и клик в центр, если необходимо.
        Возвращает True, если фокус установлен, иначе False.
        """
        try:
            if not self.window:
                self.plogging.error("Объект окна не задан (None). Не могу установить фокус.")
                return False
            try:
                if not self.window.isActive:
                    if self.window.isMinimized:
                        self.window.restore()
                        await asyncio.sleep(0.1)
                self.window.activate()
                await asyncio.sleep(0.1)

                # Проверим: действительно ли окно теперь активно
                if self.window.isActive:
                    self.plogging.info("Окно успешно активировано и находится в фокусе.")
                    await asyncio.sleep(0.2)
                    return True
                else:
                    self.plogging.warn("Окно не получило фокус после попытки activate(). Переходим к резервному варианту.")
            except Exception as activate_error:
                self.plogging.warn(f"Ошибка при попытке activate(): {activate_error}")
        except Exception as e:
            self.plogging.error(f"Ошибка при установке фокуса: {e}")
        await asyncio.sleep(0.2)
        return False
    
    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(3)
        
