import asyncio
import pyautogui
import cv2
import numpy as np
import pygetwindow as gw
from plogging import Plogging

plogging = Plogging()
plogging.set_websocket_settings(False, False, False, False)
plogging.set_folders(info='logs', error='logs', warn='logs', debug='logs')
plogging.enable_logging()


class AccountWindow:
    def __init__(self, window):
        self.window = window  # Объект окна из pygetwindow
        self.name = window.title
        # Загружаем шаблоны в оттенках серого
        self.rain_template = cv2.imread("resources/join_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.rain_joined_template = cv2.imread("resources/joined_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.match_threshold = 0.8  # Порог сопоставления шаблона

    async def focus(self):
        if self.window.isMinimized:
            self.window.restore()  # Восстанавливаем окно, если оно свернуто
            await asyncio.sleep(0.5)  # Ждем, чтобы окно восстановилось
        self.window.activate()
        await asyncio.sleep(0.5)

    async def capture_screenshot(self):
        """Делает скриншот области окна и переводит его в формат OpenCV (grayscale)."""
        bbox = (self.window.left, self.window.top, self.window.width, self.window.height)
        image = pyautogui.screenshot(region=bbox)
        frame = np.array(image)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame

    async def find_template(self, template):
        """
        Выполняет поиск шаблона в текущем окне с учетом изменения масштаба.
        Перебирает масштабы от 50% до 150% от исходного размера.
        Возвращает координаты (центра) найденного шаблона в глобальных координатах экрана,
        если совпадение выше порога, иначе None.
        """
        frame = await self.capture_screenshot()
        best_val = -1
        best_loc = None
        best_template = None
        # Перебор масштабов от 0.5 до 1.5 с шагом 0.1
        for scale in np.linspace(0.5, 1.5, 11):
            # Изменяем размер шаблона
            scaled_template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(frame, scaled_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_template = scaled_template

        if best_val >= self.match_threshold and best_loc is not None and best_template is not None:
            h, w = best_template.shape
            center_x = self.window.left + best_loc[0] + w // 2
            center_y = self.window.top + best_loc[1] + h // 2
            return (center_x, center_y)
        return None

    async def wait_for_rain(self):
        """
        Ожидает появления события (когда кнопка "Join rain" появляется в окне).
        При обнаружении возвращает координаты кнопки.
        """
        while True:
            coord = await self.find_template(self.rain_template)
            if coord:
                return coord
            # Оптимизация – проверяем каждые 1 секунду
            await asyncio.sleep(1)

    async def check_rain_joined(self):
        """
        Проверяет, изменился ли статус на "RAIN JOINED".
        Возвращает True, если статус найден, иначе False.
        """
        coord = await self.find_template(self.rain_joined_template)
        return coord is not None

    async def click_at(self, coord):
        """
        Эмулирует физический клик по указанным координатам с плавным перемещением мыши.
        """
        # Перемещаем мышь с короткой анимацией (0.1 сек)
        pyautogui.moveTo(coord[0], coord[1], duration=0.1)
        pyautogui.click()
        # Небольшая задержка после клика
        await asyncio.sleep(0.2)

    async def refresh_page(self):
        """
        Эмулирует нажатие клавиши F5 для обновления страницы.
        """
        pyautogui.press('f5')
        await asyncio.sleep(1.5)  # Ждем обновления страницы


class RainCollector:
    def __init__(self, windows):
        self.windows: list[AccountWindow] = windows

    @classmethod
    async def create(cls):
        windows = []
        for win in gw.getWindowsWithTitle("chromium"):
            if "bandit.camp" in win.title:
                await plogging.info(win.title)
                windows.append(AccountWindow(win))
        if not windows:
            await plogging.warn("Окна ungoogled‑chromium не найдены!")
        else:
            await plogging.info(f"Найдено {len(windows)} окно(а) для работы.")
        return cls(windows)

    async def run(self):
        """
        Основной бесконечный цикл, который последовательно обрабатывает каждое окно:
         - Фокусирует окно
         - Ожидает появления события (рейна)
         - Эмулирует клик по кнопке и проверяет успешность
         - При неудаче – обновляет страницу и повторяет попытку
        """
        while True:
            for account in self.windows:
                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    await plogging.info("Ожидание события рейна...")
                    # Ожидаем появления кнопки "Join rain"
                    coord = await account.wait_for_rain()
                    await plogging.info(f"Рейн обнаружен в окне {account.name} по координатам {coord}. Выполняем клик.")
                    await account.click_at(coord)
                    # Ждем N секунды для обновления статуса
                    await asyncio.sleep(7)
                    if await account.check_rain_joined():
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                    else:
                        await plogging.warn(f"В окне {account.name} не удалось присоединиться к рейну. Обновляем страницу и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        # Повторный поиск кнопки после обновления
                        coord = await account.find_template(account.rain_template)
                        if coord:
                            await account.click_at(coord)
                            await asyncio.sleep(7)
                            if await account.check_rain_joined():
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                            else:
                                await plogging.error(f"Присоединение к рейну в окне {account.name} не удалось после обновления. Пропускаем окно.")
                        else:
                            await plogging.error(f"Кнопка присоединения не найдена в окне {account.name} после обновления. Пропускаем окно.")
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")
            # После прохода по всем окнам делаем небольшую паузу перед следующим циклом
            await asyncio.sleep(1)


if __name__ == "__main__":
    async def main():
        collector = await RainCollector.create()
        await collector.run()

    asyncio.run(main())
