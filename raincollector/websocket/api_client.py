import asyncio
import json
import websockets
from typing import Any
from raincollector.utils.plogging import Plogging
from raincollector.utils import Signal


class rain_api_client:
    def __init__(self, logger: Plogging, ws_url: str = "localhost:8765"):
        self.ws_url = ws_url
        self.logger = logger
        self.connection = None
        self.rain_start = Signal()
        self.rain_scrap = Signal()
        self.rain_end = Signal()

    async def connect(self, uri=None, connection_type="raincollector"):
        if uri:
            self.ws_url = uri
        try:
            self.websocket = await websockets.connect(self.ws_url, max_size=16777216)
            self.logger.info(f"Connected to server: {self.ws_url}")
            # Отправляем начальное сообщение в JSON-формате
            initial_message = {
                "request": "INIT_CONNECTION",
                "arguments": {
                    "connection_type": connection_type
                }
            }
            await self.websocket.send(json.dumps(initial_message))
            asyncio.create_task(self.receive_messages())
        except Exception as e:
            self.logger.error(f"Connection error: {e}")

    async def disconnect(self):
        """Disconnects from the WebSocket server."""
        if self.websocket:
            try:
                await self.websocket.close()
                self.logger.info("Connection closed.")
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
        else:
            self.logger.warn("No active connection to close.")

    def isConnected(self):
        from websockets.protocol import State
        """Checks if the client is connected to the server."""
        return self.websocket is not None and self.websocket.state == State.OPEN

    async def receive_messages(self):
        """Background task to receive messages from the server."""
        try:
            while True:
                message = await self.websocket.recv()
                # Try to parse the message as JSON
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    if msg_type:
                        match msg_type:
                            case 'rain_start':
                                self.logger.info(f"Rain started: {data}")
                                self.rain_start.emit()
                            case 'rain_scrap':
                                data = data.get('message', {})
                                scrap_count = float(data.get('scrap_count'))
                                user_count = int(data.get('user_count'))
                                self.logger.info(f"Rain now: {data}")
                                self.rain_scrap.emit(scrap_count, user_count)
                            case 'rain_end':
                                data = data.get('message', {})
                                scrap_count = float(data.get('scrap_count'))
                                user_count = int(data.get('user_count'))
                                self.logger.info(f"Rain ended: {data}")
                                self.rain_end.emit(scrap_count, user_count)

                    else:
                        self.logger.warn(f"Received other message: {data}")
                except json.JSONDecodeError:
                    self.logger.error(f"Error parsing message: {message}")
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("Connection to server closed.")
        except Exception as e:
            self.logger.error(f"Error receiving messages: {e}")

    
