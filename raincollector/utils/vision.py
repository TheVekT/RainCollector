    
            
from ultralytics import YOLO
import pyautogui
import numpy as np
import cv2
from raincollector.utils.plogging import Plogging

class DetectionModel(YOLO):
    def __init__(self, model_path: str, logger: Plogging):
        super().__init__(model_path)
        self.plogging: Plogging = logger
        self.confidence_threshold = 0.7
        
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
            results = self(frame)  # вызов модели
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
                        
                        label = self.names[class_id] if hasattr(self, 'names') else str(class_id)
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
            self.plogging.error(f"Ошибка при детекции объектов: {e}")
            return {}
        
    async def find_target(self, target_name: str) -> tuple[int, int] | None:
        detections = await self.detect_objects()
        if target_name in detections:
            coords = detections[target_name]
            # Если несколько координат, берем первую
            if isinstance(coords, list):
                coords = coords[0]
            x, y, width, height = coords
            center_x = x + width // 2
            center_y = y + height // 2
            return (center_x, center_y)
        return None
        
    async def capture_screenshot(self, grayscale: bool = False):
        image = pyautogui.screenshot()  # Скриншот всего монитора
        frame = np.array(image)

        # Преобразуем RGB в BGR (PyAutoGUI возвращает RGB, OpenCV работает с BGR)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # Преобразуем в оттенки серого, если нужно

        return frame