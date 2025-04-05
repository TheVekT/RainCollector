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

        # Нет локального кэша – теперь кэш общий (в RainCollector)

        # Инициализируем YOLOv8 модель
        self.yolo_model = YOLO("best.pt")

        # Резервные шаблоны
        self.rain_template = cv2.imread("resources/join_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.rain_joined_template = cv2.imread("resources/joined_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.cloudflare_template = cv2.imread("resources/loading.jpg", cv2.IMREAD_GRAYSCALE)
        self.confirm_button_template = cv2.imread("resources/confirm_pls.jpg", cv2.IMREAD_GRAYSCALE)

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

    async def click_at(self, coord):
        pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.2)

    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(3)

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
        self.last_rain_time = time.time()
        self.rain_start_time = None
        # Глобальный кэш детекции: { window_name: { label: (center, conf, timestamp) } }
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

    async def update_global_cache(self, interval=1.0):
        """
        Фоновая задача: обновляет кэш детекции для всех окон.
        Результаты сохраняются в self.global_cache, ключ – имя окна.
        """
        while True:
            for account in self.windows:
                await account.focus()
                frame = await account.capture_screenshot(grayscale=False)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = account.yolo_model(frame_rgb)
                detections = (results[0].boxes.data.cpu().numpy() 
                              if (results and results[0].boxes.data is not None) 
                              else np.array([]))
                new_cache = {}
                for detection in detections:
                    x1, y1, x2, y2, conf, cls = detection
                    if conf >= 0.85:
                        label = account.yolo_model.model.names[int(cls)]
                        center = (account.window.left + int((x1+x2)/2),
                                  account.window.top + int((y1+y2)/2))
                        new_cache[label] = (center, conf, time.time())
                self.global_cache[account.name] = new_cache
            await asyncio.sleep(interval)

    def get_cached_detection(self, account: AccountWindow, target_label: str | tuple, max_age=1.5):
        """
        Возвращает из глобального кэша для данного окна объект с нужной меткой,
        если обновлён не более max_age секунд.
        """
        now = time.time()
        acc_cache = self.global_cache.get(account.name, {})
        if isinstance(target_label, tuple):
            for label in target_label:
                if label in acc_cache and now - acc_cache[label][2] <= max_age:
                    return (*acc_cache[label][0], label)
        else:
            if target_label in acc_cache and now - acc_cache[target_label][2] <= max_age:
                return (*acc_cache[target_label][0], target_label)
        return None

    async def wait_for_rain_for_account(self, account: AccountWindow):
        while True:
            coord = self.get_cached_detection(account, "join_rain", max_age=1.5)
            if coord:
                return coord
            await asyncio.sleep(1)

    async def check_rain_joined_for_account(self, account: AccountWindow):
        coord = self.get_cached_detection(account, "rain_joined", max_age=1.5)
        return coord is not None

    async def wait_for_rain_completion_for_account(self, account: AccountWindow, timeout=15):
        start_time = time.time()
        loading_detected = False
        while time.time() - start_time < timeout:
            if await self.check_rain_joined_for_account(account):
                return True
            cloudflare = self.get_cached_detection(account, ("cloudflare_loading", "confirm_cloudflare"), max_age=1.5)
            if cloudflare:
                loading_detected = True
                if cloudflare[2] == "confirm_cloudflare":
                    confirm = (cloudflare[0], cloudflare[1])
                    await plogging.info(f"В окне {account.name} найдена кнопка подтверждения (confirm_cloudflare). Выполняем клик.")
                    pyautogui.moveTo(confirm[0], confirm[1], duration=0.3, tween=pyautogui.easeInOutQuad)
                    pyautogui.click()
                    await asyncio.sleep(1)
                else:
                    await plogging.info(f"В окне {account.name} обнаружена загрузка (cloudflare_loading).")
            else:
                if loading_detected:
                    if await self.check_rain_joined_for_account(account):
                        await plogging.info(f"В окне {account.name} статус 'rain_joined' обнаружен после загрузки.")
                        return True
                    else:
                        await plogging.info(f"В окне {account.name} загрузка завершилась, но статус не обновился. Продолжаем ожидание.")
            await asyncio.sleep(0.5)
        return False

    async def check_bugged_windows(self):
        while True:
            await asyncio.sleep(5)
            await plogging.info("Проверяем окна на зависание...")
            for account in self.windows.copy():
                bug = self.get_cached_detection(account, "bandit_loading", max_age=1.5)
                if bug is not None:
                    await asyncio.sleep(3)
                    bug = self.get_cached_detection(account, "bandit_loading", max_age=1.5)
                    if bug is not None:
                        await plogging.info(f"Окно {account.name} зависло. Обновляем страницу.")
                        await account.refresh_page()
                        await asyncio.sleep(3)
                        await plogging.info(f"Проверяем окно {account.name} после обновления.")
                        bug = self.get_cached_detection(account, "bandit_loading", max_age=1.5)
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
        # Запускаем глобальное обновление кэша для всех окон
        global_cache_task = asyncio.create_task(self.update_global_cache(interval=1.0))
        while True:
            if time.time() - self.last_rain_time > 3600:
                await plogging.info("Прошел более часа с последнего рейна. Обновляем проблемные окна.")
                for account in self.windows:
                    if not account.rain_connected:
                        await account.refresh_page()
                self.last_rain_time = time.time()
            
            # Обработка окон последовательно: обрабатываем одно окно до завершения рейна
            for account in self.windows:
                if account.rain_connected:
                    continue

                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    if await self.check_rain_joined_for_account(account):
                        await plogging.info(f"В окне {account.name} уже присоединились к рейну.")
                        account.rain_connected = True
                        continue

                    await plogging.info(f"Ожидание появления объекта 'join_rain' в окне {account.name}...")
                    coord = await self.wait_for_rain_for_account(account)
                    if self.rain_start_time is None:
                        self.rain_start_time = time.time()
                    await plogging.info(f"В окне {account.name} обнаружен 'join_rain' по координатам {coord}. Выполняем клик.")
                    pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
                    pyautogui.click()
                    await asyncio.sleep(0.2)
                    await plogging.info(f"Ожидание завершения загрузки рейна в окне {account.name}...")
                    if await self.wait_for_rain_completion_for_account(account, timeout=15):
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                        account.rain_connected = True
                    else:
                        await plogging.warn(f"В окне {account.name} не удалось присоединиться к рейну. Обновляем окно и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        coord = self.get_cached_detection(account, "join_rain", max_age=1.5)
                        if coord:
                            pyautogui.moveTo(coord[0], coord[1], duration=0.3, tween=pyautogui.easeInOutQuad)
                            pyautogui.click()
                            await asyncio.sleep(0.2)
                            if await self.wait_for_rain_completion_for_account(account, timeout=10):
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                                account.rain_connected = True
                            else:
                                await plogging.error(f"В окне {account.name} не удалось присоединиться к рейну после обновления. Пропускаем окно.")
                        else:
                            await plogging.error(f"Объект 'join_rain' не найден в окне {account.name} после обновления. Пропускаем окно.")
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")

            if all(account.rain_connected for account in self.windows):
                await plogging.info("Все окна успешно приняли рейн, начинаем валидацию.")
                all_valid = True
                for account in self.windows:
                    if not await self.check_rain_joined_for_account(account):
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
                if self.rain_start_time and time.time() - self.rain_start_time >= 180:
                    await plogging.info("Прошло 3 минуты с начала рейна — сбрасываем статус 'rain_connected' у всех окон.")
                    for account in self.windows:
                        account.rain_connected = False
                    self.rain_start_time = None
                await asyncio.sleep(1)
    
    async def shutdown(self):
        # Отменяем глобальный таск обновления кэша
        # Можно добавить дополнительную очистку при завершении
        pass

async def main():
    collector = await RainCollector.create()
    task_run = asyncio.create_task(collector.run())
    task_reset = asyncio.create_task(collector.reset_rain_status())
    task_bugged = asyncio.create_task(collector.check_bugged_windows())
    # Запускаем глобальное обновление кэша для всех окон
    task_global_cache = asyncio.create_task(collector.update_global_cache(interval=1.0))
    await asyncio.gather(task_run, task_reset, task_bugged, task_global_cache)

if __name__ == "__main__":
    asyncio.run(main())
    