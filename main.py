import asyncio
import os
import time
from pathlib import Path
import pygetwindow as gw
import pyautogui
from raincollector.utils.plogging import Plogging
from raincollector.websocket import WebSocketServer, rain_api_client
from raincollector.models.account import AccountWindow
from raincollector.models.window import pygetWindow
from raincollector.models.websocket_client import Websocket_client
from raincollector.utils.vision import DetectionModel
from raincollector.main.rain_controller import RainController

plogging = Plogging()
plogging.set_websocket_settings(False, False, False, False)
plogging.set_folders(info='logs', error='logs', warn='logs', debug='logs')
plogging.enable_logging()

yolo_model = DetectionModel("best.pt", plogging)


async def open_browsers():
    """Открывает все ярлыки из папки accounts"""
    accounts_dir = Path(__file__).parent / "accounts"
    
    for shortcut in accounts_dir.glob("*.lnk"):
        os.startfile(str(shortcut))
        await asyncio.sleep(2)
    await asyncio.sleep(5)

async def pair_window(client: Websocket_client, paired_accounts: list[AccountWindow]):
    """Асинхронная функция для подключения клиента к окну"""
    try:
        plogging.debug(f"[PAIR] Начало pair_window для {client.profile_name}")
        plogging.debug(f"[PAIR] Ожидание 1 секунда перед поиском окна...")
        await asyncio.sleep(1)
        
        plogging.debug(f"[PAIR] Поиск окна с заголовком: {client.profile_name}")
        windows = gw.getWindowsWithTitle(client.profile_name)
        plogging.debug(f"[PAIR] Найдено окон: {len(windows)}")
        
        if not windows:
            plogging.error(f"[PAIR] ❌ Окно с заголовком '{client.profile_name}' не найдено!")
            return
        
        win = windows[0]
        plogging.debug(f"[PAIR] Используется окно: {win.title}")
        
        window = pygetWindow(win, logger=plogging)
        account_window = AccountWindow(client, window, plogging)
        account_window.extension.logger = plogging
        
        plogging.info(f"[PAIR] ✅ Paired client {client.profile_name} with window {win.title}")
        
        plogging.debug(f"[PAIR] Отправка PAIR_SUCCESSFUL...")
        await account_window.extension.pair_successful()
        plogging.debug(f"[PAIR] PAIR_SUCCESSFUL отправлен")
        
        paired_accounts.append(account_window)
        plogging.debug(f"[PAIR] Аккаунт добавлен в список. Всего: {len(paired_accounts)}")
        
    except Exception as e:
        plogging.error(f"[PAIR] ❌ Ошибка при подключении клиента {client.profile_name}: {e}")
        import traceback
        plogging.error(f"[PAIR] Traceback:\n{traceback.format_exc()}")



def _main():
    asyncio.run(main())

    
async def main_with_test():
    """Запуск основного приложения с эмуляцией тестовых сигналов рейна"""
    # Глобально объявляем rain_api чтобы использовать в dummy
    global rain_api
    
    # Функция для эмуляции сигналов рейна
    async def emit_test_rain_signals():
        """Эмулирует последовательность сигналов рейна (rain_start -> rain_scrap -> rain_end)"""
        # Деlay перед первым сигналом - даем время на инициализацию
        await asyncio.sleep(8)
        
        plogging.info("[TEST] 🧪 Эмулируем rain_start сигнал")
        rain_api.rain_start.emit()
        
        # Даем 2 сек, потом эмулируем обновления скрапа
        await asyncio.sleep(2)
        
        plogging.info("[TEST] 🧪 Эмулируем rain_scrap сигнал (scrap=20, users=100)")
        rain_api.rain_scrap.emit(800.0, 1100)
        
        
    
    # Запускаем тестовый сценарий в фоне параллельно основному приложению
    test_task = asyncio.create_task(emit_test_rain_signals())
    
    try:
        await main()
    finally:
        # Отменяем тестовую задачу если основное приложение завершилось
        if not test_task.done():
            test_task.cancel()
            try:
                await test_task
            except asyncio.CancelledError:
                pass
    

    

async def main():
    plogging.info("[MAIN] 🚀 Запуск приложения...")
    
    try:
        global rain_api
        plogging.info("[MAIN] Создание WebSocket сервера...")
        server = WebSocketServer(plogging)
        
        plogging.info("[MAIN] Запуск WebSocket сервера...")
        await server.start()
        plogging.info("[MAIN] ✅ WebSocket сервер запущен успешно")
        
        plogging.info("[MAIN] Создание rain_api клиента...")
        rain_api = rain_api_client(plogging, ws_url="ws://192.168.0.106:8765")
        
        # Подключение к rain_api в фоновой задаче (не блокируем основной поток)
        plogging.info("[MAIN] Запуск подключения к rain_api в фоне...")
        asyncio.create_task(rain_api.connect())
        
        paired_accounts: list[AccountWindow] = []
        plogging.info("[MAIN] Создание RainController...")
        raincollector = RainController(plogging, yolo_model, paired_accounts, rain_api)

        # Вызываем pair_window только после получения INIT сообщения с profile_name
        plogging.info("[MAIN] Установка callback on_client_init...")
        server.on_client_init = lambda client: pair_window(client, paired_accounts)
        
        # Обновляем информацию о вкладках в RainController (для синхронизации при открытии/переключении)
        plogging.info("[MAIN] Установка callback on_tabs_list...")
        server.on_tabs_list = lambda profile_name, tabs: raincollector.update_tabs_info(profile_name, tabs)
        
        plogging.info("[MAIN] ✅ Инициализация завершена. Ожидание подключений...")
        plogging.info("[MAIN] 📡 WebSocket сервер доступен на ws://127.0.0.1:42332")
        
        await asyncio.Event().wait()
        
    except Exception as e:
        plogging.error(f"[MAIN] ❌ Критическая ошибка в main(): {e}")
        import traceback
        plogging.error(f"[MAIN] Traceback:\n{traceback.format_exc()}")
        raise
    
if __name__ == "__main__":
    _main()
    
    
    
