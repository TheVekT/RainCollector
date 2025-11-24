import asyncio
import time
from raincollector.utils.plogging import Plogging
from raincollector.models.account import AccountWindow
from raincollector.websocket import rain_api_client
from raincollector.utils.vision import DetectionModel
from raincollector.humanizer.humanized_move import human_moveTo, Speed
from raincollector.humanizer import load_stats, predict_remaining_from_stats, BehaviorController
from datetime import datetime

# Словарь шансов сбора рейна в зависимости от времени суток и количества скрапа
# Формат: "начало-конец": {минимальный_скрап: шанс_сбора}
chance_to_collect_rains = {
    "0:00-6:00": {  # Ночь
        20: 0.1,
        50: 0.2,
        100: 0.3,
        200: 0.4,
        400: 0.5,
        600: 0.7,
        1000: 1.0
    },
    "6:00-12:00": {  # Утро
        20: 0.25,
        50: 0.3,
        100: 0.4,
        200: 0.45,
        400: 0.6,
        600: 0.8,
        1000: 1.0
    },
    "12:00-18:00": {  # День
        20: 0.5,
        50: 0.55,
        100: 0.65,
        200: 0.7,
        400: 0.8,
        600: 0.95,
        1000: 1.0
    },
    "18:00-24:00": {  # Вечер
        20: 0.7,
        50: 0.75,
        100: 0.8,
        200: 0.85,
        400: 0.9,
        600: 1.0,
        1000: 1.0
    }
}


def get_chance(scrap: float, current_time: datetime = None) -> float:
    """
    Возвращает шанс сбора рейна на основе количества скрапа и текущего времени
    
    Args:
        scrap: Количество скрапа в рейне
        current_time: Текущее время (если None - берется текущее время системы)
        
    Returns:
        Шанс сбора рейна (от 0.0 до 1.0)
        
    Example:
        >>> # Если сейчас 8:45 и скрап = 500
        >>> chance = get_chance(scrap=500)
        >>> # chance = 0.93 (из интервала "6:00-12:00")
    """
    if current_time is None:
        current_time = datetime.now()
    
    current_hour = current_time.hour
    current_minute = current_time.minute
    current_total_minutes = current_hour * 60 + current_minute
    
    # Находим подходящий временной интервал
    matching_interval = None
    for time_range, scrap_chances in chance_to_collect_rains.items():
        start_str, end_str = time_range.split('-')
        
        # Парсим начало интервала
        start_parts = start_str.split(':')
        start_hour = int(start_parts[0])
        start_minute = int(start_parts[1]) if len(start_parts) > 1 else 0
        start_total_minutes = start_hour * 60 + start_minute
        
        # Парсим конец интервала
        end_parts = end_str.split(':')
        end_hour = int(end_parts[0])
        end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0
        end_total_minutes = end_hour * 60 + end_minute
        
        # Обрабатываем случай когда интервал переходит через полночь (например, 18:00-24:00)
        if end_hour == 0 or end_hour == 24:
            end_total_minutes = 24 * 60  # конец дня
        
        # Проверяем попадание в интервал
        if start_total_minutes <= current_total_minutes < end_total_minutes:
            matching_interval = scrap_chances
            break
    
    # Если интервал не найден - возвращаем минимальный шанс
    if matching_interval is None:
        return 0.0
    
    # Находим подходящий порог скрапа
    # Сортируем пороги по возрастанию и ищем максимальный, который <= scrap
    sorted_thresholds = sorted(matching_interval.items())
    
    # Если скрап меньше самого низкого порога - возвращаем 0
    if scrap < sorted_thresholds[0][0]:
        return 0.0
    
    # Ищем подходящий шанс (берем последний порог, который <= scrap)
    chance = 0.0
    for threshold, threshold_chance in sorted_thresholds:
        if scrap >= threshold:
            chance = threshold_chance
        else:
            break
    
    return chance

class RainController:
    def __init__(self, logger: Plogging, yolo_model: DetectionModel, paired_accounts: list[AccountWindow], rain_api: rain_api_client, behavior_controller: BehaviorController):
        self.plogging = logger
        self.yolo_model = yolo_model
        self.paired_accounts = paired_accounts
        self.rain_api = rain_api
        self.current_account: AccountWindow = None
        self.behavior_controller = behavior_controller
        self.rain_now = False
        
        # Подключаем обработчики сигналов
        self.rain_api.rain_start.connect(lambda: asyncio.create_task(self.humanized_collect_rain()))
        self.current_rain_scrap = -1
        self.current_user_count = -1
        self.rain_api.rain_scrap.connect(self._set_current_rain_scrap)
        self.rain_api.rain_end.connect(lambda scrap, user_count: asyncio.create_task(self._on_rain_end(scrap, user_count)))
        self.async__init__()
        
    def async__init__(self):    
        asyncio.create_task(self.behavior_controller.start())
        
    def _set_current_rain_scrap(self, scrap: float, user_count: int):
        self.current_rain_scrap = scrap
        self.current_user_count = user_count
    
    def _extract_coords_from_detections(self, detections: dict, target_name: str) -> tuple[int, int] | None:
        """
        Извлекает координаты центра объекта из словаря детекций
        
        Args:
            detections: Словарь детекций от detect_objects()
            target_name: Название объекта для поиска
            
        Returns:
            Кортеж (center_x, center_y) или None если объект не найден
        """
        if target_name not in detections:
            return None
        
        coords = detections[target_name]
        # Если несколько координат, берем первую
        if isinstance(coords, list):
            coords = coords[0]
        x, y, width, height = coords
        center_x = x + width // 2
        center_y = y + height // 2
        return (center_x, center_y)

    async def humanized_collect_rain(self):
        """
        Обработчик сигнала rain_start - запускает процесс сбора рейна во всех окнах
        с использованием хуманизированных движений мыши
        """
        self.rain_now = True
        self.plogging.info("[RainController] Получен сигнал rain_start. Начинаем humanized_collect_rain.")
        import random
        if not self.paired_accounts:
            self.plogging.error("[RainController] Нет подключенных аккаунтов для сбора рейна.")
            return
        await asyncio.sleep(3)
        while self.current_rain_scrap < 20:
            self.plogging.info("[RainController] Ожидание обновления информации о рейне (скрап < 20).")
            await asyncio.sleep(0.5)
        
        rand = random.randrange(1, 100, 1) / 100.0
        if rand > get_chance(self.current_rain_scrap):
            self.plogging.info(f"[RainController] Шанс сбора рейна не прошел (рандом {rand:.2f} > шанс {get_chance(self.current_rain_scrap):.2f}). Пропускаем сбор.")
            return
        await self.behavior_controller.stop()
        stat_param = load_stats('stats/stats.json')
        prediction_time = predict_remaining_from_stats(stat_param, 
                                                      scrap=self.current_rain_scrap,
                                                      current_users=self.current_user_count)
        if prediction_time >= 130 and self.current_rain_scrap < 300:
            
            sleep_time = random.randint(20, 40)
            self.plogging.info(f"[RainController] Прогнозируемое время рейна {prediction_time} сек. Перед сбором ждем дополнительно {sleep_time} сек.")
            await asyncio.sleep(sleep_time)

        # Проходим по всем аккаунтам и пытаемся собрать рейн
        for account in self.paired_accounts:
            self.plogging.info(f"[RainController] Обработка аккаунта {account.extension.profile_name}.")
            self.current_account = account
            
            # Фокусируем окно аккаунта
            await account.window.focus_window()
            await asyncio.sleep(1)
            
            # Ищем join_rain или rain_joined на странице
            target_coords = None
            joined_coords = None
            for attempt in range(5):
                # Оптимизация: один вызов detect_objects вместо двух find_target
                detections = await self.yolo_model.detect_objects()
                
                # Извлекаем координаты из детекций
                joined_coords = self._extract_coords_from_detections(detections, "rain_joined")
                target_coords = self._extract_coords_from_detections(detections, "join_rain")
                
                if joined_coords:
                    self.plogging.info(f"[RainController] Аккаунт {account.extension.profile_name} уже присоединился к рейну.")
                    account.rain_connected = True
                    break
                    
                if target_coords:
                    self.plogging.info(f"[RainController] Найден join_rain для {account.extension.profile_name}. Попытка {attempt + 1}/5")
                    break
                    
                await asyncio.sleep(1)
                self.plogging.info(f"[RainController] Ожидание появления join_rain для {account.extension.profile_name}, попытка {attempt + 1}/5")
            
            # Если уже присоединен - переходим к следующему аккаунту
            if account.rain_connected:
                continue
                
            # Если join_rain не найден - пробуем обновить страницу через расширение
            if not target_coords:
                self.plogging.warn(f"[RainController] join_rain не найден для {account.extension.profile_name}. Обновляем страницу.")
                await account.window.refresh_page()
                await asyncio.sleep(3)
                
                # Повторная попытка найти join_rain
                detections = await self.yolo_model.detect_objects()
                target_coords = self._extract_coords_from_detections(detections, "join_rain")
                if not target_coords:
                    self.plogging.error(f"[RainController] join_rain не найден даже после обновления для {account.extension.profile_name}.")
                    continue
            
            # Собираем рейн с хуманизацией
            result = await self._humanized_rain_collect(account, target_coords)
            if result:
                self.plogging.info(f"[RainController] Аккаунт {account.extension.profile_name} успешно собрал рейн.")
            else:
                self.plogging.error(f"[RainController] Аккаунт {account.extension.profile_name} не смог собрать рейн.")
        
        # Валидация: проверяем, что все аккаунты получили рейн
        await self._validate_rain_collection()
        
        self.plogging.info("[RainController] Процесс humanized_collect_rain завершен.")
    
    async def _humanized_rain_collect(self, account: AccountWindow, target_coords: tuple[int, int]) -> bool:
        """
        Выполняет сбор рейна с хуманизированным движением мыши
        
        Args:
            account: AccountWindow для которого собираем рейн
            target_coords: Координаты центра кнопки join_rain (x, y)
            
        Returns:
            True если рейн успешно собран, False иначе
        """
        self.plogging.info(f"[_humanized_rain_collect] Начало сбора рейна для {account.extension.profile_name}.")
        
        # Проверяем, не присоединен ли уже аккаунт
        joined = await self._check_rain_joined(account)
        if joined:
            self.plogging.info(f"[_humanized_rain_collect] Аккаунт {account.extension.profile_name} уже присоединен.")
            account.rain_connected = True
            return True
        
        # Выполняем хуманизированный клик по кнопке join_rain
        x_coord, y_coord = target_coords
        self.plogging.info(f"[_humanized_rain_collect] Выполняем humanized click по ({x_coord}, {y_coord}) для {account.extension.profile_name}.")
        
        try:
            # Используем хуманизированное движение с случайным jitter и средней скоростью
            human_moveTo(
                x_coord, y_coord,
                speed=Speed.MEDIUM,
                jitter_range=(3, 3),  # небольшой jitter для естественности
                debug=False
            )
            await asyncio.sleep(0.15)
            # Клик уже встроен в human_moveTo через hold_button, но мы делаем отдельный клик
            import pyautogui
            pyautogui.click()
            
        except Exception as e:
            self.plogging.error(f"[_humanized_rain_collect] Ошибка при клике: {e}")
            return False
        
        await asyncio.sleep(1)
        
        # Ждем Cloudflare если появится
        await self._wait_cloudflare(account)
        await asyncio.sleep(1)
        
        # Проверяем, присоединились ли мы к рейну
        joined = await self._check_rain_joined(account)
        
        if not joined:
            self.plogging.warn(f"[_humanized_rain_collect] Рейн не подтвержден для {account.extension.profile_name} после первого клика. Пробуем еще раз.")
            
            # Обновляем страницу
            await account.window.refresh_page()
            await asyncio.sleep(3)
            
            # Ищем join_rain снова
            new_coords = None
            for i in range(3):
                detections = await self.yolo_model.detect_objects()
                new_coords = self._extract_coords_from_detections(detections, "join_rain")
                rain_joined = self._extract_coords_from_detections(detections, "rain_joined")
                if new_coords:
                    self.plogging.info(f"[_humanized_rain_collect] Найден join_rain после обновления (попытка {i+1}/3).")
                    break
                if rain_joined:
                    self.plogging.info(f"[_humanized_rain_collect] Аккаунт {account.extension.profile_name} присоединился к рейну после обновления (rain_joined найден).")
                    account.rain_connected = True
                    return True
                await asyncio.sleep(0.7)
            
            if not new_coords:
                self.plogging.error(f"[_humanized_rain_collect] join_rain не найден после обновления для {account.extension.profile_name}.")
                return False
            
            # Повторный хуманизированный клик
            x_coord, y_coord = new_coords
            self.plogging.info(f"[_humanized_rain_collect] Повторный humanized click по ({x_coord}, {y_coord}).")
            
            try:
                human_moveTo(
                    x_coord, y_coord,
                    speed=Speed.FAST,  # чуть быстрее при повторной попытке
                    jitter_range=(12, 5),
                    debug=False
                )
                await asyncio.sleep(0.15)
                import pyautogui
                pyautogui.click()
            except Exception as e:
                self.plogging.error(f"[_humanized_rain_collect] Ошибка при повторном клике: {e}")
                return False
            
            await asyncio.sleep(1)
            await self._wait_cloudflare(account)
            await asyncio.sleep(1)
            
            # Финальная проверка
            joined = await self._check_rain_joined(account)
            if not joined:
                self.plogging.error(f"[_humanized_rain_collect] Не удалось собрать рейн для {account.extension.profile_name} даже после повторной попытки.")
                return False
        
        self.plogging.info(f"[_humanized_rain_collect] Рейн успешно собран для {account.extension.profile_name}.")
        account.rain_connected = True
        return True
    
    async def _check_rain_joined(self, account: AccountWindow) -> bool:
        """
        Проверяет, присоединился ли аккаунт к рейну
        
        Returns:
            True если найден rain_joined, False если найден join_rain или ничего не найдено
        """
        async def _check_loop():
            while True:
                # Оптимизация: один вызов detect_objects вместо двух find_target
                detections = await self.yolo_model.detect_objects()
                
                # Извлекаем координаты из детекций
                rain_joined = self._extract_coords_from_detections(detections, "rain_joined")
                join_rain = self._extract_coords_from_detections(detections, "join_rain")
                
                if rain_joined:
                    self.plogging.info(f"[_check_rain_joined] Аккаунт {account.extension.profile_name} успешно присоединился (rain_joined найден).")
                    return True
                elif join_rain:
                    self.plogging.info(f"[_check_rain_joined] Аккаунт {account.extension.profile_name} еще не присоединился (join_rain найден).")
                    return False
                else:
                    self.plogging.info(f"[_check_rain_joined] Нет ни join_rain, ни rain_joined для {account.extension.profile_name}. Ожидание 1 сек.")
                    await asyncio.sleep(1)
        
        try:
            result = await asyncio.wait_for(_check_loop(), timeout=5)
            return result
        except asyncio.TimeoutError:
            self.plogging.error(f"[_check_rain_joined] Таймаут проверки для {account.extension.profile_name}.")
            return False
    
    async def _wait_cloudflare(self, account: AccountWindow):
        """
        Ожидает прохождения Cloudflare проверки и кликает по кнопке подтверждения если нужно
        """
        async def _wait_loop():
            await asyncio.sleep(1)
            while True:
                # Оптимизация: один вызов detect_objects вместо двух find_target
                detections = await self.yolo_model.detect_objects()
                
                # Извлекаем координаты из детекций
                cloudflare_loading = self._extract_coords_from_detections(detections, "cloudflare_loading")
                confirm_cloudflare = self._extract_coords_from_detections(detections, "confirm_cloudflare")
                
                if cloudflare_loading:
                    self.plogging.info(f"[_wait_cloudflare] Cloudflare загружается для {account.extension.profile_name}. Ожидание 0.7 сек.")
                    await asyncio.sleep(0.7)
                    continue
                elif confirm_cloudflare:
                    x_coord, y_coord = confirm_cloudflare
                    self.plogging.info(f"[_wait_cloudflare] Найдена кнопка Cloudflare. Хуманизированный клик по ({x_coord}, {y_coord}).")
                    
                    # Хуманизированный клик по кнопке Cloudflare
                    human_moveTo(
                        x_coord, y_coord,
                        speed=Speed.MEDIUM,
                        jitter_range=(5, 5),
                        debug=False
                    )
                    await asyncio.sleep(0.15)
                    import pyautogui
                    pyautogui.click()
                    await asyncio.sleep(1)
                    break
                else:
                    self.plogging.info(f"[_wait_cloudflare] Cloudflare завершен или не обнаружен для {account.extension.profile_name}.")
                    break
        
        try:
            await asyncio.wait_for(_wait_loop(), timeout=10)
            self.plogging.info(f"[_wait_cloudflare] Завершение для {account.extension.profile_name}.")
            return True
        except asyncio.TimeoutError:
            self.plogging.error(f"[_wait_cloudflare] Таймаут для {account.extension.profile_name}.")
            return False
    
    async def _validate_rain_collection(self):
        """
        Валидация: проверяет, что все аккаунты получили рейн, и пробует повторно для тех, кто не получил
        """
        self.plogging.info("[_validate_rain_collection] Начало валидации сбора рейна.")
        
        for account in self.paired_accounts:
            self.current_account = account
            await account.window.focus_window()
            await asyncio.sleep(2)
            
            # Проверяем наличие rain_joined
            detections = await self.yolo_model.detect_objects()
            rain_joined = self._extract_coords_from_detections(detections, "rain_joined")
            
            if rain_joined:
                self.plogging.info(f"[_validate_rain_collection] Аккаунт {account.extension.profile_name} прошел валидацию (rain_joined найден).")
                account.rain_connected = True
                continue
            
            # Если не найден - обновляем страницу и проверяем снова
            self.plogging.warn(f"[_validate_rain_collection] Аккаунт {account.extension.profile_name} не прошел валидацию. Обновляем страницу.")
            await account.window.refresh_page()
            await asyncio.sleep(3)
            
            # Ищем join_rain или rain_joined
            for i in range(5):
                # Оптимизация: один вызов detect_objects вместо двух find_target
                detections = await self.yolo_model.detect_objects()
                
                # Извлекаем координаты из детекций
                join_rain = self._extract_coords_from_detections(detections, "join_rain")
                rain_joined = self._extract_coords_from_detections(detections, "rain_joined")
                
                if join_rain or rain_joined:
                    self.plogging.info(f"[_validate_rain_collection] Найдено событие для {account.extension.profile_name}: {'rain_joined' if rain_joined else 'join_rain'} (попытка {i+1}/5).")
                    break
                    
                await asyncio.sleep(1)
            
            if rain_joined:
                self.plogging.info(f"[_validate_rain_collection] Аккаунт {account.extension.profile_name} успешно получил рейн после обновления.")
                account.rain_connected = True
                continue
            elif join_rain:
                self.plogging.warn(f"[_validate_rain_collection] Аккаунт {account.extension.profile_name} не получил рейн. Повторная попытка сбора.")
                account.rain_connected = False
                await self._humanized_rain_collect(account, join_rain)
            else:
                self.plogging.error(f"[_validate_rain_collection] Не найдены объекты для {account.extension.profile_name} даже после обновления.")
        
        # Итоговая статистика
        collected = sum(1 for acc in self.paired_accounts if acc.rain_connected)
        total = len(self.paired_accounts)
        self.plogging.info(f"[_validate_rain_collection] Валидация завершена. Собрано рейнов: {collected}/{total}")
    
    async def _on_rain_end(self, scrap_count: float, user_count: int):
        """
        Обработчик сигнала rain_end - сбрасывает состояние после окончания рейна
        """
        self.plogging.info(f"[RainController] Получен сигнал rain_end. Scrap: {scrap_count}, Users: {user_count}")
        self.rain_now = False
        self.current_rain_scrap = -1
        self.current_user_count = -1
        await self.behavior_controller.start()
        # Сбрасываем флаги rain_connected для всех аккаунтов
        for account in self.paired_accounts:
            account.rain_connected = False
            self.plogging.info(f"[RainController] Сброшено состояние для {account.extension.profile_name}.")
        
        self.plogging.info("[RainController] Готов к следующему рейну.")
