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
        self.window: gw.Win32Window = window
        self.name = get_chrome_profile_name(window)
        self.match_threshold = 0.8
        # Здесь у каждого окна есть свой экземпляр YOLO и свой кэш,
        # который обновляется фоновым таском, когда это окно активно.
        self.yolo_model = YOLO("best.pt")
        self.cache = {}
        self.cache_task = None

        self.rain_template = cv2.imread("resources/join_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.rain_joined_template = cv2.imread("resources/joined_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.cloudflare_template = cv2.imread("resources/loading.jpg", cv2.IMREAD_GRAYSCALE)
        self.confirm_button_template = cv2.imread("resources/confirm_pls.jpg", cv2.IMREAD_GRAYSCALE)

    async def start_cache(self, interval=1.0):
        self.cache_task = asyncio.create_task(self.update_cache(interval))

    async def stop_cache(self):
        if self.cache_task:
            self.cache_task.cancel()
            try:
                await self.cache_task
            except asyncio.CancelledError:
                pass
            self.cache_task = None

    async def update_cache(self, interval=1.0):
        while True:
            frame = await self.capture_screenshot(grayscale=False)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.yolo_model(frame_rgb)
            detections = results[0].boxes.data.cpu().numpy() if (results and results[0].boxes.data is not None) else np.array([])
            new_cache = {}
            for detection in detections:
                x1, y1, x2, y2, conf, cls = detection
                if conf >= 0.85:
                    label = self.yolo_model.model.names[int(cls)]
                    center = (self.window.left + int((x1+x2)/2),
                              self.window.top + int((y1+y2)/2))
                    new_cache[label] = (center, conf, time.time())
            self.cache = new_cache
            await asyncio.sleep(interval)

    async def get_cached_detection(self, target_label: str | tuple, max_age=1.5):
        now = time.time()
        if isinstance(target_label, tuple):
            for label in target_label:
                if label in self.cache and now - self.cache[label][2] <= max_age:
                    return (*self.cache[label][0], label)
        else:
            if target_label in self.cache and now - self.cache[target_label][2] <= max_age:
                return (*self.cache[target_label][0], target_label)
        return None

    async def focus(self):
        if self.window.isMinimized:
            self.window.restore()
            await asyncio.sleep(0.5)
        if not self.window.isActive:
            await plogging.warn(f"Окно профиля {self.name} не активно на экране.")
        try:
            self.window.activate()
        except Exception as e:
            await plogging.warn(f"Не удалось активировать окно профиля {self.name}: {e}")
        await asyncio.sleep(0.5)

    async def capture_screenshot(self, grayscale: bool = True):
        await self.focus()
        bbox = (self.window.left, self.window.top, self.window.width, self.window.height)
        image = pyautogui.screenshot(region=bbox)
        frame = np.array(image)
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame

    # Методы, использующие кэш:
    async def detect_object_from_cache(self, target_label: str | tuple, conf_threshold: float = 0.85):
        return await self.get_cached_detection(target_label, max_age=1.5)

    async def wait_for_rain(self):
        while True:
            coord = await self.detect_object_from_cache("join_rain", conf_threshold=0.85)
            if coord:
                return coord
            await asyncio.sleep(1)

    async def check_rain_joined(self):
        await self.focus()
        coord = await self.detect_object_from_cache("rain_joined", conf_threshold=0.85)
        return coord is not None

    async def click_at(self, coord):
        pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.2)

    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(3)

    async def wait_for_rain_completion(self, timeout=15):
        start_time = time.time()
        loading_detected = False
        while time.time() - start_time < timeout:
            if await self.check_rain_joined():
                return True
            cloudflare = await self.get_cached_detection(("cloudflare_loading", "confirm_cloudflare"), max_age=1.5)
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
                        await plogging.info("Загрузка завершилась, но статус ещё не обновлён. Продолжаем ожидание.")
            await asyncio.sleep(0.5)
        return False

class RainCollector:
    def __init__(self, windows):
        self.windows: list[AccountWindow] = windows
        self.last_rain_time = time.time()
        self.rain_start_time = None
        self.global_cache = {}
        
    @classmethod
    async def create(cls):
        windows: list[AccountWindow] = []
        for win in gw.getWindowsWithTitle("chromium"):
            if "bandit.camp" in win.title:
                await plogging.info(win.title)
                windows.append(AccountWindow(win))
        if not windows:
            await plogging.warn("Окна ungoogled‑chromium не найдены!")
        else:
            await plogging.info(f"Найдено {len(windows)} окно(а) для работы.")
            await plogging.info("Список окон:")
            for account in windows:
                account.name = f"Profile number_{windows.index(account) + 1}"
                await plogging.info(f"- {account.name}")
        return cls(windows)

    async def check_bugged_windows(self):
        while True:
            await asyncio.sleep(5)
            await plogging.info("Проверяем окна на зависание...")
            for account in self.windows.copy():
                bug = account.cache.get("bandit_loading")
                if bug is not None and time.time() - bug[2] <= 1.5:
                    await asyncio.sleep(3)
                    bug = account.cache.get("bandit_loading")
                    if bug is not None:
                        await plogging.info(f"Окно {account.name} зависло. Обновляем страницу.")
                        await account.refresh_page()
                        await asyncio.sleep(3)
                        await plogging.info(f"Проверяем окно {account.name} после обновления.")
                        bug = account.cache.get("bandit_loading")
                        if bug is not None:
                            await plogging.error(f"Окно {account.name} всё ещё зависло. Закрываем окно.")
                            account.window.close()
                            self.windows.remove(account)
            await asyncio.sleep(1)
    
    async def reset_rain_status(self):
        while True:
            await asyncio.sleep(5)
            if self.rain_start_time and time.time() - self.rain_start_time >= 180:
                await plogging.info("Прошло 3 минуты с начала рейна — сбрасываем статус 'rain_connected' у всех окон.")
                for account in self.windows:
                    account.rain_connected = False
                self.rain_start_time = None
    
    async def run(self):
        while True:
            # Если прошло больше часа с последнего рейна, обновляем проблемные окна
            if time.time() - self.last_rain_time > 3600:
                await plogging.info("Прошел более часа с последнего рейна. Обновляем проблемные окна.")
                for account in self.windows:
                    if not account.rain_connected:
                        await account.refresh_page()
                self.last_rain_time = time.time()
            
            # Последовательно обрабатываем окна: работаем только с одним окном за раз
            for account in self.windows:
                if account.rain_connected:
                    continue

                # Запускаем кэш-обновление для текущего окна
                await account.start_cache()
                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    if await account.check_rain_joined():
                        await plogging.info(f"В окне {account.name} уже присоединились к рейну.")
                        account.rain_connected = True
                        await account.stop_cache()
                        continue

                    await plogging.info(f"Ожидание появления объекта 'join_rain' в окне {account.name}...")
                    coord = await account.wait_for_rain()
                    if self.rain_start_time is None:
                        self.rain_start_time = time.time()
                    await plogging.info(f"В окне {account.name} обнаружен 'join_rain' по координатам {coord}. Выполняем клик.")
                    await account.click_at(coord)
                    await plogging.info(f"Ожидание завершения загрузки рейна в окне {account.name}...")
                    if await account.wait_for_rain_completion(timeout=15):
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                        account.rain_connected = True
                    else:
                        await plogging.warn(f"В окне {account.name} не удалось присоединиться к рейну. Обновляем окно и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        coord = account.cache.get("join_rain")
                        if coord:
                            await account.click_at(coord[0:2])
                            if await account.wait_for_rain_completion(timeout=10):
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                                account.rain_connected = True
                            else:
                                await plogging.error(f"В окне {account.name} не удалось присоединиться к рейну после обновления. Пропускаем окно.")
                        else:
                            await plogging.error(f"Объект 'join_rain' не найден в окне {account.name} после обновления. Пропускаем окно.")
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")
                await account.stop_cache()
                # После обработки одного окна выходим из цикла for, чтобы не переключаться слишком часто
                break

            # Если все окна успешно приняли рейн, проводим валидацию
            if all(account.rain_connected for account in self.windows):
                await plogging.info("Все окна успешно приняли рейн, начинаем валидацию.")
                all_valid = True
                for account in self.windows:
                    if not await account.check_rain_joined():
                        await plogging.error(f"В окне {account.name} рейн не принят при валидации.")
                        account.rain_connected = False
                        all_valid = False
                        break
                if all_valid:
                    await plogging.info("Рейн успешно принят во всех окнах. Ждём 20 минут до следующей проверки.")
                    self.last_rain_time = time.time()
                    await asyncio.sleep(20 * 60)
                    for account in self.windows:
                        account.rain_connected = False
                    self.rain_start_time = None
                else:
                    await asyncio.sleep(1)
            else:
                # Если не все окна приняли рейн, и прошло 3 минуты с начала рейна, сбрасываем статус
                if self.rain_start_time and time.time() - self.rain_start_time >= 180:
                    await plogging.info("Прошло 3 минуты с начала рейна — сбрасываем статус 'rain_connected' у всех окон.")
                    for account in self.windows:
                        account.rain_connected = False
                    self.rain_start_time = None
                await asyncio.sleep(1)

    async def update_global_cache(self, interval=1.0):
        """
        Фоновая задача для обновления глобального кэша детекции для всех окон.
        Этот метод объединяет данные из кэшей отдельных окон.
        """
        while True:
            for account in self.windows:
                # Предполагается, что каждый AccountWindow уже обновляет свой локальный кэш.
                # Обновляем глобальный кэш по имени окна.
                # Здесь просто копируем локальный кэш.
                self.global_cache[account.name] = account.cache.copy()
            await asyncio.sleep(interval)

    async def shutdown(self):
        # Здесь можно добавить логику завершения работы (отмена тасков и т.д.)
        pass

async def main():
    collector = await RainCollector.create()
    # Запускаем глобальное обновление кэша для всех окон
    task_global_cache = asyncio.create_task(collector.update_global_cache(interval=1.0))
    # Запускаем основной цикл обработки и фоновые задачи
    task_run = asyncio.create_task(collector.run())
    task_reset = asyncio.create_task(collector.reset_rain_status())
    task_bugged = asyncio.create_task(collector.check_bugged_windows())
    await asyncio.gather(task_run, task_reset, task_bugged, task_global_cache)

if __name__ == "__main__":
    asyncio.run(main())
