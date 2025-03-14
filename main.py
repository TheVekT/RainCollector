import asyncio
import time
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
        # Шаблон области Cloudflare, который появляется при загрузке/подтверждении
        self.cloudflare_template = cv2.imread("resources/loading.jpg", cv2.IMREAD_GRAYSCALE)
        # Шаблон кнопки подтверждения (например, "Я не робот")
        self.confirm_button_template = cv2.imread("resources/confirm_pls.jpg", cv2.IMREAD_GRAYSCALE)
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
        Выводит в debug-лог значение совпадения для каждого масштаба.
        Возвращает координаты (центра) найденного шаблона в глобальных координатах экрана,
        если совпадение выше порога, иначе None.
        """
        frame = await self.capture_screenshot()
        best_val = -1
        best_loc = None
        best_template = None
        for scale in np.linspace(0.5, 1.5, 11):
            scaled_template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(frame, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            await plogging.debug(f"Scale {scale:.2f}: max_val = {max_val:.3f}")
            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_template = scaled_template
        await plogging.debug(f"Best match value: {best_val:.3f}")
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
            await plogging.debug("Кнопка Join rain не найдена, повторная проверка через 1 сек.")
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
        Эмулирует физический клик по указанным координатам с «человеческим» наведением.
        """
        pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.2)

    async def refresh_page(self):
        """
        Эмулирует нажатие клавиши F5 для обновления страницы.
        """
        pyautogui.press('f5')
        await asyncio.sleep(1.5)  # Ждем обновления страницы

    async def wait_for_rain_completion(self, timeout=10):
        """
        Ожидает завершения загрузки/подтверждения рейна, т.е. появления статуса "RAIN JOINED".
        При этом, если обнаруживается область Cloudflare, ищется и нажимается кнопка подтверждения.
        Возвращает True, если статус изменился на "RAIN JOINED", иначе False по истечении timeout.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Если статус изменился, возвращаем успех
            if await self.check_rain_joined():
                return True

            # Если обнаружена область Cloudflare
            cloudflare = await self.find_template(self.cloudflare_template)
            if cloudflare:
                await plogging.info("Обнаружена область Cloudflare, требуется подтверждение.")
                # Пытаемся найти кнопку подтверждения
                confirm = await self.find_template(self.confirm_button_template)
                if confirm:
                    await plogging.info("Найдена кнопка подтверждения. Выполняем клик.")
                    await self.click_at(confirm)
                else:
                    await plogging.debug("Кнопка подтверждения не обнаружена.")
            await asyncio.sleep(0.5)
        return False


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
         В режиме debug выводятся результаты каждого этапа.
        """
        while True:
            for account in self.windows:
                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    await plogging.info("Ожидание появления кнопки Join rain...")
                    coord = await account.wait_for_rain()
                    await plogging.info(f"Кнопка Join rain обнаружена в окне {account.name} по координатам {coord}. Выполняем клик.")
                    await account.click_at(coord)
                    await plogging.info("Ожидание завершения загрузки рейна...")
                    if await account.wait_for_rain_completion(timeout=10):
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                    else:
                        await plogging.warn(f"Не удалось присоединиться к рейну в окне {account.name}. Обновляем страницу и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        # Повторный поиск кнопки Join rain после обновления
                        coord = await account.find_template(account.rain_template)
                        if coord:
                            await account.click_at(coord)
                            if await account.wait_for_rain_completion(timeout=10):
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                            else:
                                await plogging.error(f"Присоединение к рейну в окне {account.name} не удалось после обновления. Пропускаем окно.")
                        else:
                            await plogging.error(f"Кнопка Join rain не найдена в окне {account.name} после обновления. Пропускаем окно.")
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")
            await asyncio.sleep(1)


async def main():
    collector = await RainCollector.create()
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())
