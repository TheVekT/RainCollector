from typing import Optional, Dict, Any
import json
from raincollector.utils.plogging import Plogging


class Websocket_client:
    """Класс представляющий подключенного клиента к вебсокет серверу (Chrome расширение)"""
    
    def __init__(self, client_id: str, websocket, logger: Plogging):
        self.client_id = client_id
        self.websocket = websocket
        self.profile_name: Optional[str] = None
        self.is_paired = False
        self.info: Dict[str, Any] = {}
        self.logger = logger
    
    async def send(self, data: Any):
        """Отправить пакет этому клиенту"""
        try:
            # Проверяем состояние соединения
            if hasattr(self.websocket, 'state'):
                from websockets.protocol import State
                if self.websocket.state != State.OPEN:
                    self.logger.warn(f"[Client {self.profile_name or self.client_id}] ⚠️ WebSocket не открыт (state={self.websocket.state.name}), пропускаем отправку")
                    return
            
            if isinstance(data, (dict, list)):
                message = json.dumps(data, ensure_ascii=False)
            else:
                message = str(data)
            
            self.logger.debug(f"[Client {self.profile_name or self.client_id}] 📤 Отправка: {data}")
            await self.websocket.send(message)
            self.logger.debug(f"[Client {self.profile_name or self.client_id}] ✅ Отправлено успешно")
        except Exception as e:
            self.logger.error(f"[Client {self.profile_name or self.client_id}] ❌ Ошибка отправки: {e}")
            # Убрали traceback чтобы не засорять логи при закрытом соединении
    
    async def open_tab(self, url: Optional[str] = None):
        """Открыть новую вкладку в браузере клиента
        
        Args:
            url: URL для открытия (если None - откроется пустая вкладка)
        """
        command = {"type": "OPEN_TAB"}
        if url:
            command["url"] = url
        await self.send(command)
    
    async def get_tabs(self):
        """Получить список всех открытых вкладок клиента"""
        command = {"type": "GET_TABS"}
        await self.send(command)
    
    async def switch_tab(self, tab_id: int):
        """Переключиться на вкладку по ID
        
        Args:
            tab_id: ID вкладки для переключения
        """
        command = {
            "type": "SWITCH_TAB",
            "tabId": tab_id
        }
        await self.send(command)
    
    async def close_tab(self, tab_id: int):
        """Закрыть вкладку по ID
        
        Args:
            tab_id: ID вкладки для закрытия
        """
        command = {
            "type": "CLOSE_TAB",
            "tabId": tab_id
        }
        await self.send(command)
    
    async def pair_successful(self):
        """Отправить подтверждение успешного подключения (закроет вкладку профиля)"""
        command = {"type": "PAIR_SUCCESSFUL"}
        await self.send(command)
        self.is_paired = True
    
    def __repr__(self):
        return f"<Websocket_client id={self.client_id} profile={self.profile_name} paired={self.is_paired}>"
