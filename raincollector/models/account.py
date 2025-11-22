from raincollector.utils.plogging import Plogging
from raincollector.models.window import pygetWindow

from raincollector.models.websocket_client import Websocket_client
class AccountWindow():
    def __init__(self, extension: Websocket_client, window: pygetWindow, logger: Plogging):
        self.extension = extension
        self.window = window
        self.rain_connected = False
        self.logger = logger