import asyncio
import random
from typing import Dict, List, Optional
from raincollector.models.account import AccountWindow
from raincollector.utils.plogging import Plogging


class BehaviorController:
    """
    Контроллер для имитации естественного поведения пользователя в браузерах.
    Открывает/закрывает вкладки, переключается между ними, имитируя обычную активность.
    
    ВАЖНО: extension.open_tab() только ОТКРЫВАЕТ вкладку, но НЕ переключается на нее!
    После open_tab() всегда нужно:
    1. Получить обновленный список вкладок через get_tabs()
    2. Найти ID новой вкладки
    3. Переключиться на нее через switch_tab(tab_id)
    """
    
    # Список популярных сайтов для имитации browsing
    POPULAR_SITES = [
        "https://www.youtube.com",
        "https://web.telegram.org",
        "https://www.reddit.com",
        "https://twitter.com",
        "https://github.com",
        "https://stackoverflow.com",
        "https://www.wikipedia.org",
        "https://news.ycombinator.com",
        "https://www.twitch.tv",
        "https://discord.com/app",
    ]
    
    BANDIT_CAMP_URL = "https://bandit.camp/"
    
    def __init__(self, plogging: Plogging, paired_accounts: list[AccountWindow]):
        self.plogging = plogging
        self.paired_accounts = paired_accounts
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}  # profile_name -> task
        self._account_tabs: Dict[str, List[Dict]] = {}  # profile_name -> список вкладок
        self._bandit_tab_ids: Dict[str, Optional[int]] = {}  # profile_name -> tab_id bandit.camp
        
    async def start(self):
        """
        Запускает имитацию поведения для всех аккаунтов
        """
        if self._running:
            self.plogging.warn("[BehaviorController] Уже запущен.")
            return
        
        self._running = True
        self.plogging.info("[BehaviorController] Запуск имитации поведения для всех аккаунтов.")
        
        # Запускаем отдельную задачу для каждого аккаунта
        for account in self.paired_accounts:
            profile_name = account.extension.profile_name
            task = asyncio.create_task(self._behavior_loop(account))
            self._tasks[profile_name] = task
            self.plogging.info(f"[BehaviorController] Запущена имитация для {profile_name}.")
    
    async def add_account(self, account: AccountWindow):
        """
        Добавляет новый аккаунт в уже запущенный BehaviorController
        и запускает для него отдельную задачу имитации поведения
        
        Args:
            account: AccountWindow для которого нужно запустить имитацию
        """
        profile_name = account.extension.profile_name
        
        # Проверяем, не запущена ли уже задача для этого аккаунта
        if profile_name in self._tasks:
            existing_task = self._tasks[profile_name]
            if not existing_task.done():
                self.plogging.warn(f"[BehaviorController] Задача для {profile_name} уже запущена.")
                return
        
        # Добавляем аккаунт в список, если его там еще нет
        if account not in self.paired_accounts:
            self.paired_accounts.append(account)
            self.plogging.debug(f"[BehaviorController] Аккаунт {profile_name} добавлен в список.")
        
        # Запускаем задачу только если BehaviorController запущен
        if self._running:
            task = asyncio.create_task(self._behavior_loop(account))
            self._tasks[profile_name] = task
            self.plogging.info(f"[BehaviorController] ✅ Запущена имитация для нового аккаунта {profile_name}.")
        else:
            self.plogging.debug(f"[BehaviorController] Контроллер не запущен, задача для {profile_name} будет создана при start().")
    
    async def stop(self):
        """
        Останавливает имитацию поведения и возвращает все браузеры на bandit.camp
        """
        if not self._running:
            self.plogging.warn("[BehaviorController] Уже остановлен.")
            return
        
        self.plogging.info("[BehaviorController] Остановка имитации поведения.")
        self._running = False
        
        # Отменяем все задачи
        for profile_name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    self.plogging.debug(f"[BehaviorController] Задача для {profile_name} отменена.")
        
        self._tasks.clear()
        
        # Открываем/переключаемся на bandit.camp на всех аккаунтах
        self.plogging.info("[BehaviorController] Переключаемся на bandit.camp на всех аккаунтах.")
        for account in self.paired_accounts:
            try:
                profile_name = account.extension.profile_name
                
                # Получаем список вкладок
                await account.extension.get_tabs()
                await asyncio.sleep(0.5)  # Ждем получения списка вкладок
                
                tabs = self._account_tabs.get(profile_name, [])
                bandit_tab_id = None
                
                # Ищем вкладку с bandit.camp
                for tab in tabs:
                    if self.BANDIT_CAMP_URL in tab.get('url', ''):
                        bandit_tab_id = tab.get('id')
                        self.plogging.info(f"[BehaviorController] {profile_name}: найдена вкладка bandit.camp (id={bandit_tab_id})")
                        break
                
                if bandit_tab_id is not None:
                    # Вкладка существует - переключаемся на нее
                    self.plogging.info(f"[BehaviorController] {profile_name}: переключаемся на существующую вкладку bandit.camp")
                    await account.extension.switch_tab(bandit_tab_id)
                else:
                    # Вкладки нет - открываем новую и переключаемся
                    self.plogging.info(f"[BehaviorController] {profile_name}: открываем новую вкладку bandit.camp")
                    await account.extension.open_tab(self.BANDIT_CAMP_URL)
                    await asyncio.sleep(0.5)
                    
                    # После открытия получаем обновленный список вкладок и переключаемся
                    await account.extension.get_tabs()
                    await asyncio.sleep(0.5)
                    
                    tabs = self._account_tabs.get(profile_name, [])
                    for tab in tabs:
                        if self.BANDIT_CAMP_URL in tab.get('url', ''):
                            new_tab_id = tab.get('id')
                            self.plogging.info(f"[BehaviorController] {profile_name}: переключаемся на новую вкладку bandit.camp (id={new_tab_id})")
                            await account.extension.switch_tab(new_tab_id)
                            break
                
                await asyncio.sleep(0.3)  # Небольшая задержка между аккаунтами
                
            except Exception as e:
                self.plogging.error(f"[BehaviorController] Ошибка переключения на bandit.camp для {account.extension.profile_name}: {e}")
        
        self.plogging.info("[BehaviorController] Остановка завершена. Все аккаунты на bandit.camp.")
    
    async def _behavior_loop(self, account: AccountWindow):
        """
        Основной цикл имитации поведения для одного аккаунта
        
        Args:
            account: AccountWindow для которого имитируем поведение
        """
        profile_name = account.extension.profile_name
        self.plogging.info(f"[BehaviorController:{profile_name}] Начало цикла имитации.")
        
        # Параметры поведения (индивидуальные для каждого аккаунта)
        max_tabs = random.randint(2, 6)  # максимум вкладок для этого аккаунта
        browsing_speed = random.choice(["slow", "medium", "fast"])  # скорость browsing
        keep_bandit_open_chance = random.uniform(0.3, 0.7)  # вероятность держать bandit открытым
        
        self.plogging.info(
            f"[BehaviorController:{profile_name}] Параметры: "
            f"max_tabs={max_tabs}, speed={browsing_speed}, "
            f"keep_bandit_chance={keep_bandit_open_chance:.2f}"
        )
        
        try:
            while self._running:
                # Выбираем случайное действие
                action = random.choice([
                    "open_random_site",
                    "switch_tab",
                    "close_tab",
                    "idle",
                    "manage_bandit"
                ])
                
                self.plogging.debug(f"[BehaviorController:{profile_name}] Действие: {action}")
                
                try:
                    # Получаем текущее количество вкладок
                    await account.extension.get_tabs()
                    await asyncio.sleep(0.3)
                    current_tabs = self._account_tabs.get(profile_name, [])
                    tabs_count = len(current_tabs)
                    
                    if action == "open_random_site":
                        # Открываем новую вкладку только если не превышен лимит
                        if tabs_count < max_tabs:
                            await self._open_random_site(account)
                        else:
                            self.plogging.debug(f"[BehaviorController:{profile_name}] Лимит вкладок достигнут ({tabs_count}/{max_tabs}), пропускаем открытие.")
                    
                    elif action == "switch_tab":
                        await self._switch_random_tab(account)
                    
                    elif action == "close_tab":
                        # Закрываем вкладку только если их больше 1 (оставляем хотя бы одну)
                        if tabs_count > 1:
                            await self._close_random_tab(account)
                        else:
                            self.plogging.debug(f"[BehaviorController:{profile_name}] Только одна вкладка, не закрываем.")
                    
                    elif action == "manage_bandit":
                        # Случайно открываем/закрываем bandit.camp
                        bandit_tab_id = self._bandit_tab_ids.get(profile_name)
                        
                        if bandit_tab_id is None:
                            # bandit.camp не открыт, открываем с определенной вероятностью
                            if random.random() < keep_bandit_open_chance:
                                self.plogging.debug(f"[BehaviorController:{profile_name}] Открываем bandit.camp")
                                await account.extension.open_tab(self.BANDIT_CAMP_URL)
                                await asyncio.sleep(0.5)
                                
                                # Получаем обновленный список вкладок и переключаемся на bandit.camp
                                await account.extension.get_tabs()
                                await asyncio.sleep(0.5)
                                
                                tabs = self._account_tabs.get(profile_name, [])
                                for tab in tabs:
                                    if self.BANDIT_CAMP_URL in tab.get('url', ''):
                                        new_bandit_tab_id = tab.get('id')
                                        self.plogging.debug(f"[BehaviorController:{profile_name}] Переключаемся на bandit.camp (id={new_bandit_tab_id})")
                                        await account.extension.switch_tab(new_bandit_tab_id)
                                        self._bandit_tab_ids[profile_name] = new_bandit_tab_id
                                        break
                        else:
                            # bandit.camp открыт, иногда закрываем (но редко)
                            if random.random() < 0.15:  # 15% шанс закрыть
                                self.plogging.debug(f"[BehaviorController:{profile_name}] Закрываем bandit.camp (tab_id={bandit_tab_id})")
                                await account.extension.close_tab(bandit_tab_id)
                                self._bandit_tab_ids[profile_name] = None
                    
                    elif action == "idle":
                        # Просто ждем (пользователь читает страницу)
                        idle_time = random.uniform(20, 60)
                        self.plogging.debug(f"[BehaviorController:{profile_name}] Idle на {idle_time:.1f} сек")
                        await asyncio.sleep(idle_time)
                
                except Exception as e:
                    self.plogging.error(f"[BehaviorController:{profile_name}] Ошибка при выполнении действия {action}: {e}")
                
                # Задержка между действиями (зависит от скорости browsing)
                delay = self._get_delay(browsing_speed)
                await asyncio.sleep(delay)
        
        except asyncio.CancelledError:
            self.plogging.info(f"[BehaviorController:{profile_name}] Цикл имитации отменен.")
            raise
        except Exception as e:
            self.plogging.error(f"[BehaviorController:{profile_name}] Неожиданная ошибка в цикле: {e}")
    
    async def _open_random_site(self, account: AccountWindow):
        """Открывает случайный популярный сайт и переключается на него"""
        site = random.choice(self.POPULAR_SITES)
        profile_name = account.extension.profile_name
        
        self.plogging.info(f"[BehaviorController:{profile_name}] Открываем {site}")
        
        # Открываем новую вкладку
        await account.extension.open_tab(site)
        await asyncio.sleep(0.5)
        
        # Получаем обновленный список вкладок и переключаемся на новую
        await account.extension.get_tabs()
        await asyncio.sleep(0.5)
        
        tabs = self._account_tabs.get(profile_name, [])
        # Ищем вкладку с только что открытым сайтом
        for tab in tabs:
            if site in tab.get('url', ''):
                new_tab_id = tab.get('id')
                self.plogging.debug(f"[BehaviorController:{profile_name}] Переключаемся на новую вкладку (id={new_tab_id})")
                await account.extension.switch_tab(new_tab_id)
                break
    
    async def _switch_random_tab(self, account: AccountWindow):
        """Переключается на случайную вкладку"""
        profile_name = account.extension.profile_name
        
        # Запрашиваем список вкладок
        await account.extension.get_tabs()
        await asyncio.sleep(0.5)  # Даем время на получение ответа
        
        # Получаем список вкладок из кэша (если есть)
        tabs = self._account_tabs.get(profile_name, [])
        
        if not tabs:
            self.plogging.warn(f"[BehaviorController:{profile_name}] ⚠️ Нет информации о вкладках, пропускаем переключение")
            return
        
        # Выбираем случайную вкладку
        tab = random.choice(tabs)
        tab_id = tab.get('id')
        
        if tab_id is None:
            self.plogging.warn(f"[BehaviorController:{profile_name}] ⚠️ Вкладка без ID, пропускаем")
            return
        
        self.plogging.info(f"[BehaviorController:{profile_name}] Переключаемся на вкладку {tab_id} ({tab.get('title', 'Unknown')[:30]})")
        await account.extension.switch_tab(tab_id)
    
    async def _close_random_tab(self, account: AccountWindow):
        """Закрывает случайную вкладку (не bandit.camp)"""
        profile_name = account.extension.profile_name
        
        # Запрашиваем список вкладок
        await account.extension.get_tabs()
        await asyncio.sleep(0.5)
        
        tabs = self._account_tabs.get(profile_name, [])
        
        if not tabs:
            self.plogging.warn(f"[BehaviorController:{profile_name}] ⚠️ Нет информации о вкладках, пропускаем закрытие")
            return
        
        bandit_tab_id = self._bandit_tab_ids.get(profile_name)
        
        # Фильтруем вкладки, исключая bandit.camp
        closable_tabs = []
        for tab in tabs:
            tab_id = tab.get('id')
            tab_url = tab.get('url', '')
            
            # Не закрываем bandit.camp
            if tab_id != bandit_tab_id and self.BANDIT_CAMP_URL not in tab_url:
                closable_tabs.append(tab)
        
        if not closable_tabs:
            self.plogging.debug(f"[BehaviorController:{profile_name}] Нет вкладок для закрытия (только bandit.camp)")
            return
        
        # Выбираем случайную вкладку для закрытия
        tab_to_close = random.choice(closable_tabs)
        tab_id = tab_to_close.get('id')
        
        if tab_id is None:
            self.plogging.warn(f"[BehaviorController:{profile_name}] ⚠️ Вкладка без ID, пропускаем")
            return
        
        self.plogging.info(f"[BehaviorController:{profile_name}] Закрываем вкладку {tab_id} ({tab_to_close.get('title', 'Unknown')[:30]})")
        await account.extension.close_tab(tab_id)
    
    def update_tabs_info(self, profile_name: str, tabs: List[Dict]):
        """
        Обновляет информацию о вкладках для аккаунта
        (Вызывается из обработчика сообщений WebSocket при получении списка вкладок)
        
        Args:
            profile_name: Имя профиля
            tabs: Список вкладок [{'id': 123, 'url': 'https://...', 'title': '...'}]
        """
        self._account_tabs[profile_name] = tabs
        
        # Ищем tab_id для bandit.camp
        for tab in tabs:
            if self.BANDIT_CAMP_URL in tab.get('url', ''):
                self._bandit_tab_ids[profile_name] = tab.get('id')
                break
        
        self.plogging.debug(f"[BehaviorController:{profile_name}] Обновлена информация о {len(tabs)} вкладках.")
    
    def _get_delay(self, speed: str) -> float:
        """
        Возвращает задержку между действиями в зависимости от скорости browsing
        
        Args:
            speed: "slow", "medium", или "fast"
            
        Returns:
            Время задержки в секундах
        """
        if speed == "slow":
            return random.uniform(15, 45)  # 15-45 секунд
        elif speed == "medium":
            return random.uniform(8, 25)   # 8-25 секунд
        else:  # fast
            return random.uniform(3, 12)   # 3-12 секунд
    
    def is_running(self) -> bool:
        """Проверяет, запущен ли контроллер"""
        return self._running