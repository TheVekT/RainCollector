"""
Простой асинхронный WebSocket сервер на порте 42332 для Chrome Extension
- Старт/стоп сервера
- Отправка команд клиенту (расширению)
- Управление вкладками браузера
- Список подключенных профилей

Зависимости:
  pip install websockets

Использование:
  python websocket.py
"""
import asyncio
import json
import uuid
from typing import Dict, Optional, Any
import websockets
from raincollector.utils.plogging import Plogging
from raincollector.models.websocket_client import Websocket_client

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42332

# Инициализация логгера
logger = Plogging()



class WebSocketServer:
    """Простой и удобный локальный WebSocket сервер"""
    
    def __init__(self, logger: Plogging, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, ):
        self.host = host
        self.port = port
        self._server: Optional[websockets.serve] = None
        self._started = False
        self.logger = logger

        # Словарь клиентов: client_id -> Websocket_client
        self._clients: Dict[str, Websocket_client] = {}
        self.on_connect = None
        self.on_disconnect = None
        self.on_client_init = None  # Вызывается после получения INIT от клиента
        self.on_tabs_list = None  # Вызывается при получении списка вкладок
    
    async def _handler(self, ws):
        """Обработка подключения клиента"""
        client_id = str(uuid.uuid4())
        client = Websocket_client(client_id, ws, self.logger)
        self._clients[client_id] = client

        self.logger.info(f"[WS] ➕ Клиент подключен: {client_id}")
        self.logger.debug(f"[WS] Всего подключенных клиентов: {len(self._clients)}")
        self.logger.debug(f"[WS] WebSocket state: {ws.state.name if hasattr(ws, 'state') else 'unknown'}")
        
        try:
            # вызвать пользовательский обработчик подключения, если назначен
            if self.on_connect:
                self.logger.debug(f"[WS] Вызов on_connect для {client_id}")
                try:
                    await self.on_connect(client)
                    self.logger.debug(f"[WS] on_connect успешно выполнен для {client_id}")
                except Exception as e:
                    self.logger.error(f"[WS] ❌ Ошибка в on_connect: {e}")

            self.logger.debug(f"[WS] Начало цикла получения сообщений для {client_id}")
            async for message in ws:
                self.logger.debug(f"[WS] 📨 Получено сообщение от {client.profile_name or client_id}, длина: {len(message) if isinstance(message, str) else len(message)} bytes")
                
                # Обработка входящих сообщений
                try:
                    if isinstance(message, str):
                        data = json.loads(message)
                        self.logger.info(f"[WS] 📥 Получено от {client.profile_name or client_id}: {data}")
                        
                        # Обработка INIT сообщения от расширения
                        if data.get("type") == "INIT":
                            profile_name = data.get("profileName")
                            self.logger.debug(f"[WS] INIT получен с profileName: {profile_name}")
                            if profile_name:
                                client.profile_name = profile_name
                                self.logger.info(f"[WS] ✅ Клиент представился как: {profile_name}")
                                
                                # Вызвать callback после инициализации клиента
                                if self.on_client_init:
                                    self.logger.debug(f"[WS] Вызов on_client_init для {profile_name}")
                                    try:
                                        await self.on_client_init(client)
                                        self.logger.debug(f"[WS] on_client_init успешно выполнен для {profile_name}")
                                    except Exception as e:
                                        self.logger.error(f"[WS] ❌ Ошибка в on_client_init для {profile_name}: {e}")
                                else:
                                    self.logger.debug(f"[WS] on_client_init не установлен")
                                
                                # Автоматически отправляем PAIR_SUCCESSFUL
                                # await client.pair_successful()
                                # self.logger.info(f"Отправлено PAIR_SUCCESSFUL для {profile_name}")
                        
                        # Обработка PING/PONG keepalive
                        elif data.get("type") == "PING":
                            self.logger.debug(f"[WS] 🏓 PING от {client.profile_name or client_id}, отправляем PONG")
                            await client.send({"type": "PONG"})
                        
                        elif data.get("type") == "PONG":
                            self.logger.debug(f"[WS] 🏓 PONG от {client.profile_name or client_id}")
                        
                        # Обработка ответов от расширения
                        elif data.get("type") == "TAB_OPENED":
                            tab_id = data.get("tabId")
                            url = data.get("url")
                            title = data.get("title")
                            self.logger.info(f"[WS] ✅ Вкладка открыта: ID={tab_id}, URL={url}, Title={title}")
                        
                        elif data.get("type") == "TABS_LIST":
                            tabs = data.get("tabs", [])
                            self.logger.info(f"[WS] 📋 Получен список вкладок ({len(tabs)} шт):")
                            for tab in tabs:
                                self.logger.info(f"[WS]   - ID={tab['id']}: {tab['title'][:50]} ({tab['url'][:50]})")
                            
                            # Вызываем callback для обновления информации о вкладках
                            if self.on_tabs_list and client.profile_name:
                                try:
                                    # Проверяем, является ли callback async
                                    result = self.on_tabs_list(client.profile_name, tabs)
                                    if asyncio.iscoroutine(result):
                                        await result
                                except Exception as e:
                                    self.logger.error(f"[WS] ❌ Ошибка в on_tabs_list для {client.profile_name}: {e}")
                        
                        elif data.get("type") == "TAB_SWITCHED":
                            tab_id = data.get("tabId")
                            self.logger.info(f"[WS] ✅ Переключение на вкладку ID={tab_id}")
                        
                        elif data.get("type") == "TAB_CLOSED":
                            tab_id = data.get("tabId")
                            self.logger.info(f"[WS] ✅ Вкладка закрыта: ID={tab_id}")
                        
                        elif data.get("type") == "ERROR":
                            error_msg = data.get("message")
                            self.logger.error(f"[WS] ❌ Ошибка от расширения: {error_msg}")
                        
                        else:
                            self.logger.debug(f"[WS] ⚠️ Неизвестный тип сообщения: {data.get('type')}")
                    else:
                        self.logger.debug(f"[WS] 📦 Получено (binary) от {client.profile_name or client_id}: {len(message)} bytes")
                except json.JSONDecodeError as je:
                    self.logger.warn(f"[WS] ⚠️ Получено (не JSON) от {client.profile_name or client_id}: {message[:100]}")
                except Exception as msg_error:
                    self.logger.error(f"[WS] ❌ Ошибка обработки сообщения от {client.profile_name or client_id}: {msg_error}")
            
            self.logger.info(f"[WS] 🔄 Цикл async for завершён для {client.profile_name or client_id}")
            
        except websockets.exceptions.ConnectionClosed as cc:
            self.logger.info(f"[WS] 🔌 Соединение закрыто: {client.profile_name or client_id}")
            self.logger.debug(f"[WS] ConnectionClosed code={cc.code}, reason={cc.reason}")
        except Exception as handler_error:
            self.logger.error(f"[WS] ❌ Исключение в handler для {client.profile_name or client_id}: {handler_error}")
            import traceback
            self.logger.error(f"[WS] Traceback:\n{traceback.format_exc()}")
        finally:
            # Удаление клиента при отключении
            self._clients.pop(client_id, None)
            self.logger.info(f"[WS] ➖ Клиент отключен: {client.profile_name or client_id}")
            self.logger.debug(f"[WS] Осталось подключенных клиентов: {len(self._clients)}")

            # вызвать пользовательский обработчик отключения, если назначен
            if self.on_disconnect:
                self.logger.debug(f"[WS] Вызов on_disconnect для {client.profile_name or client_id}")
                try:
                    await self.on_disconnect(client)
                    self.logger.debug(f"[WS] on_disconnect успешно выполнен")
                except Exception as e:
                    self.logger.error(f"[WS] ❌ Ошибка в on_disconnect: {e}")
    
    async def start(self):
        """Запустить сервер"""
        if self._started:
            self.logger.warn(f"[WS] ⚠️ Сервер уже запущен на {self.host}:{self.port}")
            return
        
        try:
            self.logger.debug(f"[WS] Запуск WebSocket сервера на {self.host}:{self.port}")
            self._server = await websockets.serve(
                self._handler, 
                self.host, 
                self.port,
                ping_interval=20,  # Отправляем ping каждые 20 секунд
                ping_timeout=10,   # Ждем pong 10 секунд
                close_timeout=10   # Таймаут на закрытие
            )
            self._started = True
            self.logger.info(f"[WS] 🚀 Сервер запущен на ws://{self.host}:{self.port}")
            self.logger.debug(f"[WS] Сервер готов принимать подключения")
            self.logger.debug(f"[WS] Ping interval: 20s, Ping timeout: 10s")
        except OSError as e:
            if e.errno == 10048:  # Address already in use on Windows
                self.logger.error(f"[WS] ❌ Порт {self.port} уже занят! Закройте другой экземпляр или измените порт.")
            else:
                self.logger.error(f"[WS] ❌ Ошибка запуска сервера: {e}")
            raise
        except Exception as e:
            self.logger.error(f"[WS] ❌ Неожиданная ошибка запуска сервера: {e}")
            import traceback
            self.logger.error(f"[WS] Traceback:\n{traceback.format_exc()}")
            raise
    
    async def stop(self):
        """Остановить сервер"""
        if not self._started or not self._server:
            self.logger.warn("[WS] ⚠️ Сервер не запущен")
            return
        
        self.logger.info(f"[WS] 🛑 Остановка сервера...")
        self.logger.debug(f"[WS] Активных клиентов для отключения: {len(self._clients)}")
        
        # Закрыть все соединения с клиентами
        for client_id, client in list(self._clients.items()):
            try:
                self.logger.debug(f"[WS] Закрытие соединения с {client.profile_name or client_id}")
                await client.websocket.close(code=1001, reason="Сервер остановлен")
                self.logger.debug(f"[WS] Соединение закрыто для {client.profile_name or client_id}")
            except Exception as e:
                self.logger.error(f"[WS] ❌ Ошибка при закрытии клиента {client_id}: {e}")
        
        # Остановить сервер
        self.logger.debug("[WS] Закрытие серверного сокета")
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self._started = False
        self._clients.clear()
        self.logger.info("[WS] ✅ Сервер остановлен")
    
    async def send(self, client_id: str, data: Any) -> bool:
        """Отправить пакет конкретному клиенту"""
        client = self._clients.get(client_id)
        if not client:
            self.logger.warn(f"Клиент {client_id} не найден")
            return False
        
        await client.send(data)
        return True
    
    async def broadcast(self, data: Any) -> int:
        """Отправить пакет всем подключенным клиентам"""
        sent_count = 0
        for client_id, client in list(self._clients.items()):
            try:
                await client.send(data)
                sent_count += 1
            except Exception as e:
                self.logger.error(f"Ошибка отправки клиенту {client_id}: {e}")
        
        self.logger.info(f"Рассылка выполнена: {sent_count}/{len(self._clients)} клиентов")
        return sent_count
    
    def list_clients(self) -> Dict[str, Websocket_client]:
        """Получить список всех подключенных клиентов"""
        return self._clients.copy()
    
    def get_client_by_profile(self, profile_name: str) -> Optional[Websocket_client]:
        """Получить клиента по имени профиля"""
        for client in self._clients.values():
            if client.profile_name == profile_name:
                return client
        return None
    
    def list_profiles(self) -> Dict[str, Websocket_client]:
        """Получить список клиентов с установленным профилем"""
        return {client.profile_name: client for client in self._clients.values() if client.profile_name}
    
    def num_clients(self) -> int:
        """Количество подключенных клиентов"""
        return len(self._clients)

