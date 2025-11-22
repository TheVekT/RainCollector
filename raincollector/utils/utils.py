class Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        """Подключает функцию-обработчик к сигналу."""
        self._slots.append(slot)

    def emit(self, *args, **kwargs):
        """Вызывает все подключенные функции-обработчики."""
        try:
            for slot in self._slots:
                slot(*args, **kwargs)
        except Exception as e:
            print(f"Error in signal slot: {e}")
        