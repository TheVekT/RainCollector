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

def get_chrome_profile_name(window):
    """
    Пытается извлечь имя профиля Chromium из аргументов командной строки процесса.
    Если не удаётся, возвращает window.title.
    """
    try:
        # Получаем дескриптор окна (hWnd)
        hwnd = window._hWnd
        # Получаем PID процесса, которому принадлежит окно
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
        # Ищем аргумент с profile-directory
        for arg in cmdline:
            if arg.startswith("--profile-directory="):
                # Например, "--profile-directory=Profile 1"
                return arg.split("=", 1)[1]
        # Если параметр не найден, возвращаем title окна
        return window.title
    except Exception as e:
        return window.title

class AccountWindow:
    def __init__(self, window):
        self.window = window  # Объект окна из pygetwindow
        self.name = get_chrome_profile_name(window)  # Имя профиля Chromium
        self.match_threshold = 0.8  # Порог сопоставления (для шаблонов, если нужны)

        # Инициализируем YOLOv8 модель.
        # Укажите корректный путь к вашему файлу модели.
        self.yolo_model = YOLO("best.pt")

        # Если шаблоны нужны для каких-то резервных случаев, их можно оставить.
        self.rain_template = cv2.imread("resources/join_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.rain_joined_template = cv2.imread("resources/joined_button.jpg", cv2.IMREAD_GRAYSCALE)
        self.cloudflare_template = cv2.imread("resources/loading.jpg", cv2.IMREAD_GRAYSCALE)
        self.confirm_button_template = cv2.imread("resources/confirm_pls.jpg", cv2.IMREAD_GRAYSCALE)

    async def focus(self):
        if self.window.isMinimized:
            self.window.restore()
            await asyncio.sleep(0.5)
        if not self.window.isActive:
            await plogging.warn(f"Окно {self.name} не видно на экране.")
        try:
            self.window.activate()
        except Exception as e:
            await plogging.warn(f"Не удалось активировать окно {self.name}: {e}")
        await asyncio.sleep(0.5)

    async def capture_screenshot(self, grayscale: bool = True):
        """
        Делает скриншот области окна и возвращает изображение.
        Если grayscale=True, то конвертирует изображение в оттенки серого.
        """
        bbox = (self.window.left, self.window.top, self.window.width, self.window.height)
        image = pyautogui.screenshot(region=bbox)
        frame = np.array(image)
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame

    async def detect_object_yolo(self, target_label: str | tuple, conf_threshold: float = 0.9):
        """
        Выполняет детектирование с помощью YOLOv8.
        Захватываем цветной скриншот, переводим его в формат RGB и запускаем инференс.
        Если найден объект с нужной меткой и уверенностью выше порога, возвращаем
        координаты центра объекта с учётом позиции окна.
        """
        # Получаем цветной скриншот для детектирования
        frame = await self.capture_screenshot(grayscale=False)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.yolo_model(frame_rgb)

        # Обрабатываем результаты инференса (предполагается, что результаты в results[0].boxes.data)
        detections = results[0].boxes.data.cpu().numpy() if results and results[0].boxes.data is not None else np.array([])
        print(detections)
        for detection in detections:
            x1, y1, x2, y2, conf, cls = detection
            if conf >= conf_threshold:
                # Получаем метку класса, предполагается, что модель хранит имена классов в model.names
                label = self.yolo_model.model.names[int(cls)]
                if label == target_label or label in target_label:
                    center_x = self.window.left + int((x1 + x2) / 2)
                    center_y = self.window.top + int((y1 + y2) / 2)
                    return (center_x, center_y, label) if isinstance(target_label, tuple) else (center_x, center_y)
        return None

    async def wait_for_rain(self):
        """
        Ожидает появления объекта с меткой "join_rain".
        Возвращает координаты найденного объекта.
        """
        while True:
            coord = await self.detect_object_yolo("join_rain", conf_threshold=0.9)
            if coord:
                return coord
            await plogging.debug("Объект 'join_rain' не обнаружен, повторная проверка через 1 сек.")
            await asyncio.sleep(1)

    async def check_rain_joined(self):
        """
        Проверяет, изменился ли статус на "rain_joined" с помощью YOLO.
        Возвращает True, если объект найден, иначе False.
        """
        coord = await self.detect_object_yolo("rain_joined", conf_threshold=0.9)
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
        await asyncio.sleep(1.5)

    async def wait_for_rain_completion(self, timeout=15):
        """
        Ожидает завершения загрузки/подтверждения рейна.
        Логика:
          - Сначала проверяем, появился ли статус "rain_joined".
          - Если нет, ищем индикаторы загрузки: "cloudflare_loading" или "confirm_cloudflare".
          - Если найден "confirm_cloudflare", выполняем клик по нему.
          - Ждем, пока индикаторы загрузки исчезнут, после чего проверяем, изменился ли статус на "rain_joined".
        """
        start_time = time.time()
        loading_detected = False
        while time.time() - start_time < timeout:
            # Если статус изменился на "rain_joined", считаем рейн успешно принят.
            if await self.check_rain_joined():
                return True

            # Проверяем наличие индикаторов загрузки
            cloudflare = await self.detect_object_yolo(("cloudflare_loading", "confirm_cloudflare"), conf_threshold=0.9)

            if cloudflare:
                loading_detected = True
                if cloudflare[2] == "confirm_cloudflare":
                    confirm = (cloudflare[0], cloudflare[1])
                    await plogging.info("Найдена кнопка подтверждения (confirm_cloudflare). Выполняем клик.")
                    await self.click_at(confirm)
                    await asyncio.sleep(1)  # Ждём после клика
                else:
                    await plogging.info("Загрузка активна (cloudflare_loading обнаружен).")
            else:
                if loading_detected:
                    # Если ранее была загрузка, а теперь индикаторы исчезли, проверяем статус
                    if await self.check_rain_joined():
                        print("\n\nrain joined\n\n")
                        return True
                    else:
                        await plogging.info("Загрузка завершилась, но статус еще не обновлен. Продолжаем ожидание.")
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
        Основной цикл: для каждого окна
          - Фокусируем окно
          - Ожидаем появления объекта "join_rain" (с помощью YOLO)
          - Выполняем клик и проверяем успешное завершение
          - При неудаче обновляем страницу и повторяем попытку
        Если рейн успешно принят во всех окнах, ждём 20 минут (1200 секунд)
        """
        while True:
            cycle_success = True  # Флаг успешной обработки всех окон в цикле
            for account in self.windows:
                await account.focus()
                await plogging.info(f"Проверяем окно: {account.name}")
                try:
                    await plogging.info("Ожидание появления объекта 'join_rain'...")
                    print(f"\n\n{account.name}\n\n")
                    coord = await account.wait_for_rain()
                    await plogging.info(f"Объект 'join_rain' обнаружен в окне {account.name} по координатам {coord}. Выполняем клик.")
                    await account.click_at(coord)
                    await plogging.info("Ожидание завершения загрузки рейна...")
                    if await account.wait_for_rain_completion(timeout=15):
                        await plogging.info(f"В окне {account.name} успешно присоединились к рейну.")
                    else:
                        await plogging.warn(f"Не удалось присоединиться к рейну в окне {account.name}. Обновляем страницу и повторяем попытку.")
                        await account.refresh_page()
                        await asyncio.sleep(1)
                        coord = await account.detect_object_yolo("join_rain", conf_threshold=0.9)
                        if coord:
                            await account.click_at(coord)
                            if await account.wait_for_rain_completion(timeout=10):
                                await plogging.info(f"В окне {account.name} успешно присоединились к рейну после обновления.")
                            else:
                                await plogging.error(f"Присоединение к рейну в окне {account.name} не удалось после обновления. Пропускаем окно.")
                                cycle_success = False
                        else:
                            await plogging.error(f"Объект 'join_rain' не найден в окне {account.name} после обновления. Пропускаем окно.")
                            cycle_success = False
                except Exception as e:
                    await plogging.error(f"Ошибка в окне {account.name}: {e}")
                    cycle_success = False

            if cycle_success:
                await plogging.info("Рейн успешно принят во всех окнах. Ждём 20 минут до следующей проверки.")
                await asyncio.sleep(20 * 60)  # 20 минут
            else:
                # Если хоть в одном окне произошла ошибка, делаем короткую паузу и продолжаем цикл
                await asyncio.sleep(1)


async def main():
    collector = await RainCollector.create()
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())
