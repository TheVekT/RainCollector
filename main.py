import asyncio
import time
import pyautogui
import cv2
import numpy as np
import pygetwindow as gw
import psutil
import win32process
from plogging import Plogging
from ultralytics import YOLO  # Импорт модели YOLOv8

plogging = Plogging()
plogging.set_websocket_settings(False, False, False, False)
plogging.set_folders(info='logs', error='logs', warn='logs', debug='logs')
plogging.enable_logging()

def get_chrome_profile_name(window) -> str:
    """
    Пытается извлечь имя профиля Chromium из аргументов командной строки процесса.
    Если не удаётся, возвращает window.title.
    """
    try:
        hwnd = window._hWnd
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
        for arg in cmdline:
            if arg.startswith("--profile-directory="):
                return arg.split("=", 1)[1]
        return window.title
    except Exception as e:
        return window.title

class AccountWindow:
    def __init__(self, window):
        self.rain_connected = False
        self.window = window
        # Используем имя профиля вместо заголовка
        self.name = get_chrome_profile_name(window)
        self.match_threshold = 0.8

        # Инициализируем YOLOv8 модель (путь к модели укажите корректно)
        self.yolo_model = YOLO("best.pt")

        # Резервные шаблоны (если потребуются)
        self.rain_template = cv2.imread("resources/join_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.rain_joined_template = cv2.imread("resources/joined_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.cloudflare_template = cv2.imread("resources/loading.jpg", cv2.IMREAD_GRAYSCALE)
        self.confirm_button_template = cv2.imread("resources/confirm_pls.jpg", cv2.IMREAD_GRAYSCALE)

    async def focus(self):
        if self.window.isMinimized:
            self.window.restore()
            await asyncio.sleep(0.5)
        # Проверка: окно должно быть активно и видно
        if not self.window.isActive or not self.window.isVisible():
            await plogging.warn(f"Окно профиля {self.name} не активно или не видно на экране.")
        try:
            self.window.activate()
        except Exception as e:
            await plogging.warn(f"Не удалось активировать окно профиля {self.name}: {e}")
        await asyncio.sleep(0.5)

    async def capture_screenshot(self, grayscale: bool = True):
        bbox = (self.window.left, self.window.top, self.window.width, self.window.height)
        image = pyautogui.screenshot(region=bbox)
        frame = np.array(image)
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame

    async def detect_object_yolo(self, target_label: str | tuple, conf_threshold: float = 0.9):
        frame = await self.capture_screenshot(grayscale=False)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.yolo_model(frame_rgb)
        detections = results[0].boxes.data.cpu().numpy() if results and results[0].boxes.data is not None else np.array([])
        for detection in detections:
            x1, y1, x2, y2, conf, cls = detection
            if conf >= conf_threshold:
                label = self.yolo_model.model.names[int(cls)]
                if label == target_label or (isinstance(target_label, tuple) and label in target_label):
                    center_x = self.window.left + int((x1 + x2) / 2)
                    center_y = self.window.top + int((y1 + y2) / 2)
                    return (center_x, center_y, label) if isinstance(target_label, tuple) else (center_x, center_y)
        return None

    async def wait_for_rain(self):
        while True:
            coord = await self.detect_object_yolo("join_rain", conf_threshold=0.9)
            if coord:
                return coord
            await asyncio.sleep(1)

    async def check_rain_joined(self):
        coord = await self.detect_object_yolo("rain_joined", conf_threshold=0.9)
        return coord is not None

    async def click_at(self, coord):
        pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.2)

    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(1.5)

    async def wait_for_rain_completion(self, timeout=15):
        start_time = time.time()
        loading_detected = False
        while time.time() - start_time < timeout:
            if await self.check_rain_joined():
                return True
            cloudflare = await self.detect_object_yolo(("cloudflare_loading", "confirm_cloudflare"), conf_threshold=0.9)
            if cloudflare:
                loading_detected = True
                if cloudflare[2] == "confirm_cloudflare":
                    confirm = (cloudflare[0], cloudflare[1])
                    await plogging.info("Найдена кнопка подтверждения (confirm_cloudflare). Выполняем клик.")
                    await self.click_at(confirm)
                    await asyncio.sleep(1)
                else:
                    await plogging.info("Загрузка активна (cloudflare_loading обнаружен).")
            else:
                if loading_detected:
                    if await self.check_rain_joined():
                        await plogging.info("Статус 'rain_joined' обнаружен после загрузки.")
                        return True
                    else:
                        await plogging.info("Загрузка завершилась, но статус еще не обновлен. Продолжаем ожидание.")
            await asyncio.sleep(0.5)
        return False

    async def find_template(self, template):
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

class RainCollector:
    def __init__(self, windows):
        self.windows: list[AccountWindow] = windows
        self.last_rain_time = time.time()  # время последнего успешного рейна

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
        while True:
            # Если прошло больше часа с последнего рейна, обновляем проблемные окна
            if time.time() - self.last_rain_time > 3600:
                await plogging.info("Прошел более часа с последнего рейна. Обновляем проблемные окна.")
                for account in self.windows:
                    if not account.rain_connected:
                        await account.refresh_page()
                # Обновляем время, чтобы не делать refresh слишком часто
                self.last_rain_time = time.time()
            
            for account in self.windows:
                # Обрабатываем только окна, где рейн еще не принят
                if account.rain_connected:
                    continue

                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    if await account.check_rain_joined():
                        await plogging.info(f"В окне {account.name} уже присоединились к рейну.")
                        account.rain_connected = True
                        continue

                    await plogging.info("Ожидание появления объекта 'join_rain'...")
                    coord = await account.wait_for_rain()
                    await plogging.info(f"Объект 'join_rain' обнаружен в окне {account.name} по координатам {coord}. Выполняем клик.")
                    await account.click_at(coord)
                    await plogging.info("Ожидание завершения загрузки рейна...")
                    if await account.wait_for_rain_completion(timeout=15):
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                        account.rain_connected = True
                    else:
                        await plogging.warn(f"Не удалось присоединиться к рейну в окне {account.name}. Обновляем окно и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        coord = await account.detect_object_yolo("join_rain", conf_threshold=0.9)
                        if coord:
                            await account.click_at(coord)
                            if await account.wait_for_rain_completion(timeout=10):
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                                account.rain_connected = True
                            else:
                                await plogging.error(f"Присоединение к рейну в окне {account.name} не удалось после обновления. Пропускаем окно.")
                        else:
                            await plogging.error(f"Объект 'join_rain' не найден в окне {account.name} после обновления. Пропускаем окно.")
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")

            # Если все окна успешно приняли рейн, ждем 20 минут
            if all(account.rain_connected for account in self.windows):
                await plogging.info("Рейн успешно принят во всех окнах. Ждём 20 минут до следующей проверки.")
                await asyncio.sleep(20 * 60)  # 20 минут
                # Сбрасываем флаг для нового цикла
                for account in self.windows:
                    account.rain_connected = False
            else:
                # Если не во всех окнах рейн принят, делаем короткую паузу и повторяем цикл
                await asyncio.sleep(1)


async def main():
    collector = await RainCollector.create()
    await collector.run()

if __name__ == "__main__":
    asyncio.run(main())
