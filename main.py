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
from tasks import loop



plogging = Plogging()
plogging.set_websocket_settings(False, False, False, False)
plogging.set_folders(info='logs', error='logs', warn='logs', debug='logs')
plogging.enable_logging()

class AccountWindow:
    def __init__(self, window: gw.Win32Window, name: str = "Unnamed"):
        self.rain_connected = False
        self.window: gw.Win32Window = window
        self.name = name
        
    async def focus_window(self):
        """
        Ставит фокус на окно (pygetwindow.Win32Window).
        Использует .activate(), .bringToFront() и клик в центр, если необходимо.
        Возвращает True, если фокус установлен, иначе False.
        """
        try:
            if not self.window:
                await plogging.error("Объект окна не задан (None). Не могу установить фокус.")
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
                    await plogging.info("Окно успешно активировано и находится в фокусе.")
                    return True
                else:
                    await plogging.warn("Окно не получило фокус после попытки activate(). Переходим к резервному варианту.")
            except Exception as activate_error:
                await plogging.warn(f"Ошибка при попытке activate(): {activate_error}")

            # Резервный способ — клик в центр окна
            try:
                left = self.window.left
                top = self.window.top
                width = self.window.width
                height = self.window.height
                center_x = left + width // 2
                center_y = top + height // 2
                pyautogui.click(center_x, center_y)
                await asyncio.sleep(0.3)

                if self.window.isActive:
                    await plogging.info(f"Фокус установлен через клик по координатам ({center_x}, {center_y}).")
                    return True
                else:
                    await plogging.warn("Клик выполнен, но окно не стало активным.")
            except Exception as click_error:
                await plogging.error(f"Не удалось установить фокус кликом: {click_error}")

        except Exception as e:
            await plogging.error(f"Ошибка при установке фокуса: {e}")
        
        return False
    
    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(3)
        
        
        
class RainCollector:
    def __init__(self, Yolo: YOLO):
        self.windows: list[AccountWindow] = []
        self.start_rain_time = time.time()
        self.yolo = Yolo
        self.current_detections = {}
        self.confidence_threshold = 0.86
        self.rain_now = False
        self.current_window = None
        
    async def update_windows(self):
        windows: list[AccountWindow] = []
        for win in gw.getWindowsWithTitle("chromium"):
            if "bandit.camp" in win.title:
                await plogging.info(win.title)
                windows.append(AccountWindow(win))
        if not windows:
            await plogging.warn("Окна ungoogled‑chromium не найдены!")
        else:
            await plogging.info(f"Найдено {len(windows)} окно(а) для работы.")
            await plogging.info("Список окон: ")
            for account in windows:
                account.name = f"Profile number_{windows.index(account) + 1}"
                await plogging.info(f"- {account.name}")
        self.windows = windows

    async def capture_screenshot(self, window: AccountWindow, grayscale: bool = False):
        await window.focus_window()
        await asyncio.sleep(1)
        bbox = (window.window.left, window.window.top, window.window.width, window.window.height)
        image = pyautogui.screenshot(region=bbox)
        frame = np.array(image)
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame
    
    async def isLoading(self, window: AccountWindow) -> bool:
        """
        Проверяет, загружено ли окно (по наличию текста "Loading..." в заголовке окна).
        Возвращает True, если окно загружено, иначе False.
        """
        try:
            if window.window.isActive:
                tmp = self.current_detections.get("bandit_loading", None)
                if tmp:
                    return True
                elif not tmp:
                    return False
            else:
                await plogging.warn(f"{window.name} - Окно не активно. Не могу проверить загрузку.")
                return False
        except Exception as e:
            await plogging.error(f"Ошибка при проверке загрузки окна: {e}")
            return False
        
    async def wait_cloudflare(self):
        async def _wait_cloudflare_loop():
            while True:
                cloudflare_loading = self.current_detections.get("cloudflare_loading", None)
                confirm_cloudflare = self.current_detections.get("confirm_cloudflare", None)
                if cloudflare_loading:
                    await asyncio.sleep(0.7)
                    continue
                elif confirm_cloudflare:
                    await self.click(confirm_cloudflare[0]+confirm_cloudflare[2]//2, confirm_cloudflare[1]+confirm_cloudflare[3]//2)
                    await asyncio.sleep(0.5)
                    break
                else:
                    await plogging.info(f"Cloudflare в окне {self.current_window.name} закончился или не обнаружен.")
                    break
        try:
            await asyncio.wait_for(_wait_cloudflare_loop(), timeout=10)
            return True
        except asyncio.TimeoutError:
            await plogging.error(f"Cloudflare в окне {self.current_window.name} не завершился вовремя.")
            return False
    
        
    async def click(self, x: int, y: int):
        """
        Кликает по координатам (x, y) на экране.
        """
        pyautogui.moveTo(x, y, duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.2)
    
    async def check_rain_joined(self):
        async def _check_rain_joined_loop():
            while True:
                rain_joined = self.current_detections.get("rain_joined", None)
                join_rain = self.current_detections.get("join_rain", None)
                if rain_joined:
                    await plogging.info(f"Окно {self.current_window.name} присоединилось к рейну.")
                    break
                elif join_rain:
                    await plogging.info(f"Окно {self.current_window.name} не смогло присоединиться к рейну.")
                    return False
                else:
                    await asyncio.sleep(0.7)
        try:
            await asyncio.wait_for(_check_rain_joined_loop(), timeout=3)
            return True
        except asyncio.TimeoutError:
            await plogging.error(f"Не удалось проверить присоединиться ли к рейну в окне {self.current_window.name}")
            return False
    
    async def rain_collect(self, coords):
        if await self.check_rain_joined():
            await plogging.info(f"Окно {self.current_window.name} уже присоеденено к рейну.")
            self.current_window.rain_connected = True
            return True
        await self.click(coords[0]+coords[2]//2, coords[1]+coords[3]//2)
        await self.wait_cloudflare()
        if not await self.check_rain_joined():
            await self.current_window.refresh_page()
            rain = self.current_detections.get("join_rain", None)
            if rain:
                await self.click(rain[0]+rain[2]//2, rain[1]+rain[3]//2)
                await self.wait_cloudflare()
                if not await self.check_rain_joined():
                    return False
        else:
            self.current_window.rain_connected = True
            return True
    
    @loop(seconds=0.7)
    async def update_detections(self):
        if not self.current_window:
            self.windows[0].focus_window()
            self.current_window = self.windows[0]
        self.current_detections = await self.detect_objects(self.current_window)
        
    @loop(seconds=900)
    async def ref_page(self):
        if self.current_window and not self.rain_now:
            await self.current_window.refresh_page()
        else:
            await plogging.error("Нет активного окна для обновления страницы.")
    
    @loop(seconds=900)       
    async def check_bug_window(self):
        bugged = self.current_detections.get("bandit_loading", None)
        if bugged:
            await asyncio.sleep(3)
            if self.current_detections.get("bandit_loading", None):
                await plogging.info(f"Обнаружено, что окно {self.current_window.name} зависло. Пробуем обновить страницу.")
                await self.current_window.refresh_page()
                if self.current_detections.get("bandit_loading", None):
                    await plogging.error(f"Не удалось обновить страницу в окне {self.current_window.name} с первого раза.")
                    await asyncio.sleep(3)
                    await self.current_window.refresh_page()
                    if self.current_detections.get("bandit_loading", None):
                        await plogging.error(f"Не удалось обновить страницу в окне {self.current_window.name} со второго раза. Помечаем окно как зависшее.")
                        self.windows.remove(self.current_window)
                        self.current_window = self.windows[0]
                        return False
                    else:
                        await plogging.info(f"Страница в окне {self.current_window.name} обновлена успешно.")
                        return True
                else:
                    return True
    
    async def run(self):
        if not self.windows:
            await plogging.error("Нет доступных окон для работы.")
            raise ValueError("Нет доступных окон для работы.")
        self.update_detections.start()
        self.ref_page.start()
        self.check_bug_window.start()
        
        self.current_window = self.windows[0]
        while True:
            await self.current_window.focus_window()
            rain = self.current_detections.get("join_rain", None)
            joined = self.current_detections.get("rain_joined", None)
            while not rain or not joined:
                await asyncio.sleep(0.7)
                rain = self.current_detections.get("join_rain", None)
                joined = self.current_detections.get("rain_joined", None)
            if rain:
                self.start_rain_time = time.time()
                while time.time() - self.start_rain_time < 180:
                    self.rain_now = True
                    await plogging.info("Рейн обнаружен")
                    for window in self.windows:
                        self.current_window = window
                        await window.focus_window()
                        await asyncio.sleep(0.5)
                        rain = self.current_detections.get("join_rain", None)
                        rain_joined = self.current_detections.get("rain_joined", None)
                        if rain_joined:
                            await plogging.info(f"Окно {window.name} уже присоеденено к рейну.")
                            self.current_window.rain_connected = True
                            continue
                        if not rain:
                            await plogging.error(f"Не удалось найти рейн в окне {window.name} хотя рейн идет.")
                            await window.refresh_page()
                            await asyncio.sleep(0.7)
                            rain = self.current_detections.get("join_rain", None)
                            if not rain:
                                await plogging.error(f"Не удалось найти рейн в окне {window.name} даже после обновления страницы.")
                                continue
                            else:
                                await self.rain_collect(rain)
                            continue
                        await self.rain_collect(rain)
                    await plogging.info("Предварительнов все окна присоединились к рейну. Валидация.")
                    for window in self.windows:
                        self.current_window = window
                        await window.focus_window()
                        await asyncio.sleep(0.7)
                        rain_joined = self.current_detections.get("rain_joined", None)  
                        if rain_joined:
                            await plogging.info(f"При валидации, обнаружено что {window.name} присоеденено к рейну.")
                            self.current_window.rain_connected = True
                            continue
                        elif self.current_detections.get("join_rain", None):
                            await plogging.info(f"При валидации, обнаружено что {window.name} не присоеденено к рейну. Пробуем присоединиться.")
                            self.current_window.rain_connected = False
                            await self.rain_collect(self.current_detections.get("join_rain", None))
                            continue
                    if all(window.rain_connected for window in self.windows):
                        await plogging.info("Все окна успешно присоединились к рейну.")
                self.rain_now = False
                await plogging.info("Рейн закончился")
                for window in self.windows:
                    window.rain_connected = False  
                await plogging.info("Ожидаем 20 минут до следующего рейна.")
                await asyncio.sleep(1200)
                await plogging.info("20 минут ожидания завершены. Проверяем окна на наличие рейна.")    
                
                        
                
                
            
        
    async def detect_objects(self, window: AccountWindow, grayscale: bool = False) -> dict:
        """
        Захватывает скриншот окна (с помощью метода capture_screenshot),
        пропускает изображение через модель YOLOv8 (ultralytics) и возвращает словарь с детекциями.
        
        Формат словаря:
        { 'название_объекта': [(x, y, width, height), ...], ... }
        
        Если детекций нет, возвращается пустой словарь.
        """
        try:
            # Захватываем скриншот через существующий метод
            frame = await self.capture_screenshot(window, grayscale)

            # Если требуется, преобразуем изображение в формат BGR для OpenCV (ultralytics YOLO ожидает RGB, как правило)
            # Но обычно YOLO из ultralytics принимает NumPy-массивы в формате BGR или RGB, в зависимости от модели.
            # Здесь предположим, что frame в RGB формате, как возвращает pyautogui.screenshot()

            # Вызываем модель напрямую (YOLOv8 возвращает список результатов)
            results = self.yolo(frame)  # вызов модели
            # Инициализируем словарь для результатов
            detection_dict = {}
            
            # Обрабатываем все результаты (предполагается, что results - список объектов Result)
            # Каждый result имеет атрибуты .boxes и .names
            for result in results:
                # Получаем boxes (объекты обнаружений)
                boxes = result.boxes
                # Обходим каждое обнаружение
                for box in boxes:
                    # Получаем confidence и class id
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    
                    if confidence > self.confidence_threshold:
                        # box.xyxy содержит координаты [x1, y1, x2, y2]
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        x = int(x1)
                        y = int(y1)
                        width = int(x2 - x1)
                        height = int(y2 - y1)
                        
                        # Получаем название объекта (для YOLOv8 Ultralytics, модель хранит классы в self.yolo.names)
                        # Убедитесь, что self.yolo.names определены. Если нет, задайте их вручную.
                        label = self.yolo.names[class_id] if hasattr(self.yolo, 'names') else str(class_id)
                        
                        # Добавляем детекцию в словарь
                        if label in detection_dict:
                            detection_dict[label].append((x, y, width, height))
                        else:
                            detection_dict[label] = [(x, y, width, height)]
            
            return detection_dict

        except Exception as e:
            # Логируем ошибку, если что-то пошло не так
            await plogging.error(f"Ошибка при детекции объектов: {e}")
            return {}

        except Exception as e:
            # Логируем ошибку, если что-то пошло не так
            await plogging.error(f"Ошибка при детекции объектов: {e}")
            return {}
        
async def main():
    yolo_model = YOLO("best.pt")
    collector = RainCollector(Yolo=yolo_model)
    await collector.update_windows()
    await collector.run()
    


if __name__ == "__main__":
    asyncio.run(main())
