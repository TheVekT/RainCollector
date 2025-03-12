import os
import gzip
import datetime
import json

class Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        """Подключает функцию-обработчик к сигналу."""
        self._slots.append(slot)

    def emit(self, *args, **kwargs):
        """Вызывает все подключенные функции-обработчики."""
        for slot in self._slots:
            slot(*args, **kwargs)


class Plogging:
    _instance = None  # Class-level instance
    _initialized = False  # To prevent re-initialization

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Plogging, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.logs_dir = os.path.normpath("./logs")
        self.config_file = os.path.join(self.logs_dir, "logging_config.json")
        if self._initialized:
            return  # Prevent re-initialization

        
        
        self.last_log_date = self._get_current_date()
        self.log_history = []
        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)
        # Flag to prevent recursion in logging
        self.recursion_guard = False
        self.last_log_message = ""
        self.on_log_message = Signal()
        # Settings for folders for different log levels
        self.log_folders = {
            'info': os.path.normpath(self.logs_dir),
            'error': os.path.normpath(self.logs_dir),
            'debug': os.path.normpath(self.logs_dir),
            'warn': os.path.normpath(self.logs_dir),
        }
        # Paths to current log files
        self.log_filepaths = {
            'info': None,
            'error': None,
            'debug': None,
            'warn': None,
        }
        self._wb_translate = {
            'info': True,
            'error': True,
            'debug': True,
            'warn': True,
        }
        # Load settings from file if it exists
        self.load_log_settings()
        self._initialized = True  # Mark as initialized

    def _get_log_filename(self):
        """Возвращает имя файла журнала на основе текущего времени."""
        time_now_logs = datetime.datetime.now()
        formatted_time_logs = time_now_logs.strftime("%d-%m-%Y_%H-%M-%S")
        return f"log_{formatted_time_logs}.txt"

    def create_log_file(self, level):
        """Создает новый файл журнала для указанного уровня и возвращает путь к нему."""
        log_filename = self._get_log_filename()
        folder = os.path.normpath(self.log_folders[level])  # Нормализуем путь папки
        if not os.path.exists(folder):
            os.makedirs(folder)
        self.log_filepaths[level] = os.path.join(folder, log_filename)
        
        try:
            with open(self.log_filepaths[level], 'w') as f:
                pass
            print(f"Log file created: {self.log_filepaths[level]} for level: {level}")
        except Exception as e:
            print(f"Error on creating log file: {e}")

    def set_folders(self, info=None, error=None, debug=None, warn=None):
        """
        Настраивает папки для каждого уровня логов.
        Если передано несколько уровней с одинаковыми значениями, они будут писать в один файл.
        """
        if info:
            self.log_folders['info'] = os.path.normpath(os.path.join(self.logs_dir, info))
        if error:
            self.log_folders['error'] = os.path.normpath(os.path.join(self.logs_dir, error))
        if debug:
            self.log_folders['debug'] = os.path.normpath(os.path.join(self.logs_dir, debug))
        if warn:
            self.log_folders['warn'] = os.path.normpath(os.path.join(self.logs_dir, warn))

        # Сохраняем настройки в JSON файл
        self.save_log_settings()

    def archive_logs(self):
        """Архивирует старые файлы журнала и удаляет их."""
        for level, folder in self.log_folders.items():
            # Нормализуем путь
            folder = os.path.normpath(folder)
            if not os.path.exists(folder):
                print(f"Folder '{folder}' does not exist. Skipping...")
                continue

            log_files = [file for file in os.listdir(folder) if file.endswith(".txt")]

            if log_files:
                for file in log_files:
                    archive_filename = f"{file[:-4]}_archive.gz"
                    archive_filepath = os.path.join(folder, archive_filename)

                    with open(os.path.join(folder, file), 'rb') as f_in, gzip.open(archive_filepath, 'wb') as f_out:
                        f_out.writelines(f_in)
                    
                    os.remove(os.path.join(folder, file))
                    print(f"Log file {file} successfully zipped in {archive_filepath}")

    def set_websocket_settings(self, info=True, error=True, debug=True, warn=True):
        """Настраивает параметры WebSocket для каждого уровня логов."""
        self._wb_translate = {
            'info': info,
            'error': error,
            'debug': debug,
            'warn': warn,
        }
        # Сохраняем обновленные настройки WebSocket
        self.save_log_settings()
        
    def enable_logging(self):
        """Включает логирование, архивирует старые файлы и создает новый файл журнала для всех уровней."""
        self.archive_logs()
        for level in self.log_filepaths.keys():
            self.create_log_file(level)

    def _get_current_date(self):
        """Возвращает текущую дату в формате YYYY-MM-DD."""
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def save_log_settings(self):
        """Сохраняет текущие настройки папок логов в JSON файл."""
        # Нормализуем пути перед сохранением
        settings = {
            'log_folders': {
                'info': os.path.normpath(self.log_folders['info']),
                'error': os.path.normpath(self.log_folders['error']),
                'debug': os.path.normpath(self.log_folders['debug']),
                'warn': os.path.normpath(self.log_folders['warn']),
            },
            'websocket_settings': {
                'info': self._wb_translate['info'],
                'error': self._wb_translate['error'],
                'debug': self._wb_translate['debug'],
                'warn': self._wb_translate['warn'],
            }
        }
        try:
            with open(self.config_file, 'w') as json_file:
                json.dump(settings, json_file)
            print(f"Log settings saved to {self.config_file}")
        except Exception as e:
            print(f"Error saving log settings: {e}")


    def load_log_settings(self):
        """Загружает настройки логирования и WebSocket из JSON файла, если файл существует."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as json_file:
                    settings = json.load(json_file)
                    
                    # Загружаем папки логов
                    self.log_folders['info'] = os.path.normpath(settings.get('log_folders', {}).get('info', self.logs_dir))
                    self.log_folders['error'] = os.path.normpath(settings.get('log_folders', {}).get('error', self.logs_dir))
                    self.log_folders['debug'] = os.path.normpath(settings.get('log_folders', {}).get('debug', self.logs_dir))
                    self.log_folders['warn'] = os.path.normpath(settings.get('log_folders', {}).get('warn', self.logs_dir))
                    
                    # Загружаем настройки WebSocket
                    self._wb_translate['info'] = settings.get('websocket_settings', {}).get('info', True)
                    self._wb_translate['error'] = settings.get('websocket_settings', {}).get('error', True)
                    self._wb_translate['debug'] = settings.get('websocket_settings', {}).get('debug', True)
                    self._wb_translate['warn'] = settings.get('websocket_settings', {}).get('warn', True)

                    print(f"Log and WebSocket settings loaded from {self.config_file}")
            except Exception as e:
                print(f"Error loading log settings: {e}")
        else:
            print(f"No log settings file found. Using default settings.")

    async def _log(self, level, text):
        """Общий метод логирования для всех уровней."""
        if self.recursion_guard:
            print(f"Recursion prevented: {text}")
            return
        try:
            current_date = self._get_current_date()
            if current_date != self.last_log_date:
                # Дата изменилась, архивируем текущие файлы и создаем новые
                self.archive_logs()
                for lvl in self.log_filepaths.keys():
                    self.create_log_file(lvl)
                self.last_log_date = current_date

            # Логируем сообщение
            time_now = datetime.datetime.now()
            formatted_time = time_now.strftime("%H:%M:%S")
            self.last_log_message = f"[{formatted_time}][{level.upper()}]: {text}"
            if self._wb_translate[level] == True:
                self.log_history.append(self.last_log_message)
                self.on_log_message.emit()
                
            print(self.last_log_message)
            log_file_path = self.log_filepaths[level]
            with open(log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"{self.last_log_message}\n")
        except Exception as e:
            self.recursion_guard = True
            print(f"Error in plogging: {e}")
            self.recursion_guard = False

    async def info(self, text):
        await self._log("info", text)

    async def error(self, text):
        await self._log("error", text)

    async def debug(self, text):
        await self._log("debug", text)

    async def warn(self, text):
        await self._log("warn", text)

    def get_history(self):
        return list(self.log_history) if self.log_history is not None else "Log history clear."

    def get_last_log_message(self):
        return str(self.log_history[-1])
