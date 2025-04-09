import asyncio
import asyncio.selector_events
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
                    await asyncio.sleep(0.2)
                    return True
                else:
                    await plogging.warn("Окно не получило фокус после попытки activate(). Переходим к резервному варианту.")
            except Exception as activate_error:
                await plogging.warn(f"Ошибка при попытке activate(): {activate_error}")
        except Exception as e:
            await plogging.error(f"Ошибка при установке фокуса: {e}")
        await asyncio.sleep(0.2)
        return False
    
    async def refresh_page(self):
        pyautogui.press('f5')
        await asyncio.sleep(3)
        
        
        
class RainCollector:
    def __init__(self, Yolo: YOLO):
        self.windows: list[AccountWindow] = []
        self.start_rain_time = None
        self.yolo = Yolo
        self.current_detections = {}
        self.confidence_threshold = 0.7
        self.rain_now = False
        self.current_window = None
        self.rain_start_time = None
        
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

    async def capture_screenshot(self, grayscale: bool = False):
        if not self.current_window.window.isActive:
            await self.current_window.focus_window()  # Если нужно, оставьте фокус на окне
        image = pyautogui.screenshot()  # Скриншот всего монитора
        frame = np.array(image)

        # Преобразуем RGB в BGR (PyAutoGUI возвращает RGB, OpenCV работает с BGR)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Преобразуем в оттенки серого, если нужно

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
            await asyncio.sleep(2)
            while True:
                cloudflare_loading = self.current_detections.get("cloudflare_loading", None)
                confirm_cloudflare = self.current_detections.get("confirm_cloudflare", None)
                if cloudflare_loading:
                    await plogging.info(f"[cloudflare-001] В окне {self.current_window.name} найден индикатор загрузки Cloudflare. Ожидание 0.7 сек.")
                    await asyncio.sleep(0.7)
                    continue
                elif confirm_cloudflare:
                    # Вычисляем координаты центра кнопки подтверждения
                    x_coord = confirm_cloudflare[0] + confirm_cloudflare[2] // 2
                    y_coord = confirm_cloudflare[1] + confirm_cloudflare[3] // 2
                    await plogging.info(f"[cloudflare-002] В окне {self.current_window.name} найден confirm_cloudflare. Выполняем клик по координатам: {x_coord}:{y_coord}.")
                    await self.click(x_coord, y_coord)
                    await asyncio.sleep(1)
                    break
                else:
                    await plogging.info(f"[cloudflare-003] Cloudflare в окне {self.current_window.name} завершился или не обнаружен. Выход из цикла ожидания.")
                    break
        try:
            await asyncio.wait_for(_wait_cloudflare_loop(), timeout=10)
            await plogging.info(f"[cloudflare-004] Завершение wait_cloudflare в окне {self.current_window.name}.")
            return True
        except asyncio.TimeoutError:
            await plogging.error(f"[cloudflare-005] Cloudflare в окне {self.current_window.name} не завершился вовремя (таймаут).")
            return False
    
        
    async def click(self, x: int, y: int):
        """
        Кликает по координатам (x, y) на экране.
        """
        await plogging.info(f"[click-001] Выполняется клик по координатам: {x}:{y} в окне {self.current_window.name}.")
        pyautogui.moveTo(x, y, duration=0.3, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        await asyncio.sleep(0.3)
        await plogging.info(f"[click-002] Завершён клик в окне {self.current_window.name}.")
    
    async def check_rain_joined(self):
        async def _check_rain_joined_loop():
            while True:
                rain_joined = self.current_detections.get("rain_joined", None)
                join_rain = self.current_detections.get("join_rain", None)
                if rain_joined:
                    await plogging.info(f"[rain_joined-001] Окно {self.current_window.name} успешно присоединилось к рейну (rain_joined обнаружен).")
                    return True
                elif join_rain:
                    await plogging.info(f"[rain_joined-002] Окно {self.current_window.name} еще не присоединилось к рейну (обнаружен join_rain).")
                    return False
                else:
                    await plogging.info(f"[rain_joined-003] В окне {self.current_window.name} отсутствуют как join_rain, так и rain_joined. Ожидание 1 сек.")
                    await asyncio.sleep(1)
        try:
            result = await asyncio.wait_for(_check_rain_joined_loop(), timeout=5)
            await plogging.info(f"[rain_joined-004] Завершение проверки рейна в окне {self.current_window.name}.")
            return result
        except asyncio.TimeoutError:
            await plogging.error(f"[rain_joined-005] Не удалось проверить присоединение к рейну в окне {self.current_window.name} (таймаут).")
            return False
    
    async def rain_collect(self, coords):
        await plogging.info(f"[rain_collect-001] Начало процедуры сбора рейна в окне {self.current_window.name}.")
        connected = await self.check_rain_joined()
        await plogging.info(f"[rain_collect-002] Статус присоедененности {connected}, поданные кординаты обькта рейна {coords}")
        if connected == True:
            await plogging.info(f"[rain_collect-003] Окно {self.current_window.name} уже получило рейн. Выход из процедуры.")
            self.current_window.rain_connected = True
            return True
        await plogging.info(f"[rain_collect-math-001] Пытаемся высщитать координаты клика.")
        try:
            x_coord = coords[0] + coords[2] // 2
            y_coord = coords[1] + coords[3] // 2
        except Exception as e:
            await plogging.error(f"[rain_collect-error] Ошибка вычисления координат: {e}. coords: {coords}")
            return False
        await plogging.info(f"[rain_collect-004] Выполняем первичный клик по центру join_rain: {x_coord}:{y_coord} в окне {self.current_window.name}.")
        await self.click(x_coord, y_coord)
        await asyncio.sleep(2)
        await plogging.info(f"[rain_collect-005] Ждём Cloudflare после первичного клика в окне {self.current_window.name}.")
        await self.wait_cloudflare()
        await asyncio.sleep(1)
        connected = await self.check_rain_joined() 
        if connected == False:
            await plogging.info(f"[rain_collect-006] Рейн не подтвержден в окне {self.current_window.name} после первого клика. Обновляем страницу.")
            await self.current_window.refresh_page()
            for i in range(3):
                rain = self.current_detections.get("join_rain", None)
                if rain:
                    await plogging.info(f"[rain_collect-007] Найден join_rain после обновления страницы в окне {self.current_window.name} (попытка {i+1}/3).")
                    break
                else:
                    await asyncio.sleep(0.7)
                    await plogging.info(f"[rain_collect-008] Нет join_rain в окне {self.current_window.name} после обновления, ожидание 0.7 сек (попытка {i+1}/3).")
            if rain:
                x_coord = rain[0] + rain[2] // 2
                y_coord = rain[1] + rain[3] // 2
                await plogging.info(f"[rain_collect-009] Выполняем повторный клик по join_rain: {x_coord}:{y_coord} в окне {self.current_window.name}.")
                await self.click(x_coord, y_coord)
                await asyncio.sleep(2)
                await plogging.info(f"[rain_collect-010] Ждём Cloudflare после повторного клика в окне {self.current_window.name}.")
                await self.wait_cloudflare()
                await asyncio.sleep(1)
                if not await self.check_rain_joined():
                    await plogging.error(f"[rain_collect-011] Окно {self.current_window.name} так и не подтвердило получение рейна после повторного клика.")
                    return False
            else:
                await plogging.error(f"[rain_collect-012] join_rain не найдено в окне {self.current_window.name} после обновления страницы.")
                return False
        else:
            await plogging.info(f"[rain_collect-013] Окно {self.current_window.name} успешно подтвердило получение рейна после первичного клика.")
            self.current_window.rain_connected = True
            return True
    
    async def update_detections(self):
        while True:
            await asyncio.sleep(0.7)
            if not self.current_window:
                self.windows[0].focus_window()
                self.current_window = self.windows[0]
            print(self.current_detections)
            self.current_detections = await self.detect_objects()
        
    async def ref_page(self):
        while True:
            await asyncio.sleep(900)
            if self.current_window and not self.rain_now:
                await self.current_window.refresh_page()
            else:
                await plogging.error("Нет активного окна для обновления страницы.")
            
    async def check_bug_window(self):
        while True:
            await asyncio.sleep(900)
            bugged = self.current_detections.get("bandit_loading", None)
            if bugged:
                await plogging.info(f"[bug-001] Окно {self.current_window.name} обнаружило 'bandit_loading'. Ожидание 3 сек для повторной проверки.")
                await asyncio.sleep(3)
                if self.current_detections.get("bandit_loading", None):
                    await plogging.info(f"[bug-002] Окно {self.current_window.name} до сих пор в состоянии 'bandit_loading'. Попытка обновления страницы (1-я попытка).")
                    await self.current_window.refresh_page()
                    if self.current_detections.get("bandit_loading", None):
                        await plogging.error(f"[bug-003] Первичная попытка обновления страницы не удалась в окне {self.current_window.name}. Ожидание 3 сек и повторная попытка.")
                        await asyncio.sleep(3)
                        await self.current_window.refresh_page()
                        if self.current_detections.get("bandit_loading", None):
                            await plogging.error(f"[bug-004] Окно {self.current_window.name} так и не восстановилось после двух попыток обновления. Помечаем окно как зависшее и удаляем его из списка.")
                            self.windows.remove(self.current_window)
                            if self.windows:
                                self.current_window = self.windows[0]
                                await plogging.info(f"[bug-005] Переключаемся на окно {self.current_window.name} как новое активное окно.")
                            else:
                                await plogging.error("[bug-006] Нет доступных окон после удаления зависшего. Завершение проверки.")
                            return False
                        else:
                            await plogging.info(f"[bug-007] Окно {self.current_window.name} успешно восстановилось после второй попытки обновления.")
                            return True
                    else:
                        await plogging.info(f"[bug-008] Окно {self.current_window.name} восстановилось после первой попытки обновления.")
                        return True
    
    async def run(self):
        # Проверка наличия доступных окон
        if not self.windows:
            await plogging.error("Ошибка [init-001]: Нет доступных окон для работы.")
            raise ValueError("Нет доступных окон для работы.")


        # Инициализируем первое окно
        self.current_window = self.windows[0]
        await plogging.info("Старт [init-002]: Первое окно выбрано для начала работы.")

        while True:
            # Фокусируем текущее окно
            await self.current_window.focus_window()
            await asyncio.sleep(3)
            await plogging.info(f"Фокус окна [cycle-001]: Окно {self.current_window.name} получило фокус.")

            # Ждём появления хотя бы одного из объектов: join_rain или rain_joined.
            rain = self.current_detections.get("join_rain", None)
            joined = self.current_detections.get("rain_joined", None)
            while rain is None and joined is None:
                await asyncio.sleep(1)
                rain = self.current_detections.get("join_rain", None)
                joined = self.current_detections.get("rain_joined", None)
                if rain:
                    await asyncio.sleep(1)
                    rain = self.current_detections.get("join_rain", None)
                    if rain:
                        break
            
            # Фиксируем время начала рейна (если ещё не зафиксировано)
            if self.rain_start_time is None:
                self.rain_start_time = time.time()
                await plogging.info("Таймстамп [time-001]: Фиксируем время начала рейна.")

            # Режим сбора рейна в течение 3 минут
            while time.time() - self.rain_start_time < 180:
                self.rain_now = True
                await plogging.info("Обработка [rain-001]: Рейн обнаружен, начинаем обработку окон.")

                # Проходим по всем окнам для попытки присоединения к рейну
                for window in self.windows:
                    await plogging.info(f"Обработка окон [loop-001]: Переключаемся на окно {window.name}.")
                    self.current_detections = {}  # Сброс детекций для нового окна
                    self.current_window = window
                    await window.focus_window()
                    await asyncio.sleep(3)
                    await plogging.info(f"Фокус окна [loop-002]: Фокус установлен для окна {window.name}.")

                    # Обновляем данные глобального кэша для текущего окна с повторными попытками
                    for i in range(5):
                        rain = self.current_detections.get("join_rain", None)
                        rain_joined = self.current_detections.get("rain_joined", None)
                        if rain or rain_joined:
                            await plogging.info(f"Проверка кэша [cache-001]: В окне {window.name} обнаружено событие: {'rain_joined' if rain_joined else 'join_rain'}.")
                            break
                        else:
                            await asyncio.sleep(1)
                            await plogging.info(f"Ожидание кэша [cache-002]: Нет данных в окне {window.name}, повторная проверка ({i+1}/4).")

                    # Если окно уже присоединилось к рейну, пропускаем его
                    if rain_joined:
                        await plogging.info(f"Пропуск окна [skip-001]: Окно {window.name} уже получило рейн (rain_joined обнаружен).")
                        window.rain_connected = True
                        continue

                    # Если объект join_rain не найден – пробуем обновить страницу
                    if not rain:
                        await plogging.error(f"Ошибка [refresh-001]: В окне {window.name} не найден join_rain, хотя рейн идет. Пытаемся обновить страницу.")
                        await window.refresh_page()
                        for i in range(5):
                            rain = self.current_detections.get("join_rain", None)
                            if rain:
                                await plogging.info(f"Обновление кэша [refresh-002]: join_rain обнаружен в окне {window.name} после обновления (попытка {i+1}/4).")
                                break
                            else:
                                await asyncio.sleep(1)
                                await plogging.info(f"Ожидание после обновления [refresh-003]: Нет join_rain в окне {window.name}, повторная проверка ({i+1}/4).")
                        if not rain:
                            await plogging.error(f"Ошибка [refresh-004]: join_rain так и не найден в окне {window.name} после обновления страницы.")
                            continue
                        else:
                            result = await self.rain_collect(rain)
                            if result == True:
                                await plogging.info(f"Присоединение [collect-001]: В окне {window.name} выполнено присоединение рейна после обновления.")
                            else:
                                await plogging.info(f"Пропуск окна [skip-002]: Окно {window.name} не смогло даже после обновления присоединится.")
                            continue

                    # Если обнаружен объект join_rain – пробуем принять рейн
                    await plogging.info(f"Присоединение [collect-002]: Запущено присоединение рейна в окне {window.name} по объекту join_rain.")
                    await self.rain_collect(rain)
                    

                # Валидация: Проверяем, получили ли все окна рейн
                await plogging.info("Валидация [validate-001]: Начало проверки окон на получение рейна.")
                for window in self.windows:
                    self.current_window = window
                    await window.focus_window()
                    for i in range(4):
                        rain_joined = self.current_detections.get("rain_joined", None)
                        if rain or rain_joined:
                            break
                        else:
                            await asyncio.sleep(1)
                    if rain_joined:
                        continue
                    await self.current_window.refresh_page()
                    await plogging.info(f"Валидация [validate-002]: Фокус установлен для проверки окна {window.name}.")
                    await asyncio.sleep(3)
                    result = await self.check_rain_joined()
                    if rain_joined:
                        await plogging.info(f"Валидация [validate-003]: Окно {window.name} успешно получило рейн.")
                        window.rain_connected = True
                        continue
                    else:
                        for i in range(5):
                            rain = self.current_detections.get("join_rain", None)
                            rain_joined = self.current_detections.get("rain_joined", None)
                            if rain or rain_joined:
                                await plogging.info(f"Проверка кэша [validate-cache-001]: В окне {window.name} обнаружено событие: {'rain_joined' if rain_joined else 'join_rain'}.")
                                break
                            else:
                                await asyncio.sleep(1)
                                await plogging.info(f"Ожидание кэша [validate-cache-002]: Нет данных в окне {window.name}, повторная проверка ({i+1}/4).")
                        if rain:
                            await plogging.info(f"Валидация [validate-004]: Окно {window.name} не получило рейн, пробуем повторное присоединение.")
                            window.rain_connected = False
                            await self.rain_collect(self.current_detections.get("join_rain", None))
                            continue
                        elif rain_joined:
                            await plogging.info(f"Валидация [validate-003]: Окно {window.name} успешно получило рейн.")
                            window.rain_connected = True
                            continue
                

                # Если все окна получили рейн, завершаем цикл сбора рейна
                if all(window.rain_connected for window in self.windows):
                    await plogging.info("Завершение цикла [cycle-002]: Все окна получили рейн в текущем цикле.")
                else:
                    await plogging.info("Завершение цикла [cycle-003]: НЕ все окна получили рейн в текущем цикле.")
                break
            # По истечении 3 минут режима рейна: сбрасываем флаги и начинаем ожидание до следующего рейна
            self.rain_now = False
            await plogging.info("Завершение процеса[end-001]: Рейн закончен или процесс сбора окончен, сбрасываем состояние окон.")
            for window in self.windows:
                window.rain_connected = False
                await plogging.info(f"Сброс состояния [end-002]: Сброшено состояние для окна {window.name}.")
            await plogging.info("Ожидание [wait-001]: Начинается 20-минутное ожидание до следующего рейна.")
            await asyncio.sleep(20 * 60)
            await plogging.info("Ожидание завершено [wait-002]: 20 минут прошли, начинаем новый цикл.")
            self.rain_start_time = None
                    
                        
                
                
            
        
    async def detect_objects(self, grayscale: bool = False) -> dict:
        """
        Захватывает скриншот окна (с помощью метода capture_screenshot),
        пропускает изображение через модель YOLOv8 (ultralytics) и возвращает словарь с детекциями.
        
        Формат словаря:
        { 'название_объекта': [(x, y, width, height), ...], ... }
        
        Если детекций нет, возвращается пустой словарь.
        """
        try:
            # Захватываем скриншот через существующий метод
            frame = await self.capture_screenshot(grayscale)

            # Если требуется, преобразуем изображение в формат BGR для OpenCV (ultralytics YOLO ожидает RGB, как правило)
            # Но обычно YOLO из ultralytics принимает NumPy-массивы в формате BGR или RGB, в зависимости от модели.
            # Здесь предположим, что frame в RGB формате, как возвращает pyautogui.screenshot()

            # Вызываем модель напрямую (YOLOv8 возвращает список результатов)
            results = self.yolo(frame)  # вызов модели
            # Инициализируем словарь для результатов
            detection_dict = {}

            for result in results:
                boxes = result.boxes
                for box in boxes:
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])

                    if confidence > self.confidence_threshold:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        x = int(x1)
                        y = int(y1)
                        width = int(x2 - x1)
                        height = int(y2 - y1)
                        
                        label = self.yolo.names[class_id] if hasattr(self.yolo, 'names') else str(class_id)
                        coords = (x, y, width, height)

                        if label not in detection_dict:
                            detection_dict[label] = coords  # просто кортеж
                        else:
                            # если уже есть кортеж — преобразуем в список
                            if isinstance(detection_dict[label], tuple):
                                detection_dict[label] = [detection_dict[label], coords]
                            else:
                                detection_dict[label].append(coords)
            
            return detection_dict

        except Exception as e:
            # Логируем ошибку, если что-то пошло не так
            await plogging.error(f"Ошибка при детекции объектов: {e}")
            return {}

async def main():
    yolo_model = YOLO("best.pt")
    collector = RainCollector(Yolo=yolo_model)
    await collector.update_windows()
    asyncio.create_task(collector.check_bug_window())
    asyncio.create_task(collector.update_detections())
    asyncio.create_task(collector.ref_page())
    asyncio.create_task(collector.run())
    await asyncio.Event().wait()
    


if __name__ == "__main__":
    asyncio.run(main())
