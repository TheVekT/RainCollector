from enum import Enum
import math
import random
import time
from typing import Tuple, Optional, List

import pyautogui
import numpy as np

pyautogui.FAILSAFE = True  # можно отключить, но полезно при разработке

class Speed(Enum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"

def _minimum_jerk_scale(s: float) -> float:
    """Классическая полиномиальная шкала minimum-jerk для s in [0,1]."""
    # 10*s^3 - 15*s^4 + 6*s^5
    return 10*s**3 - 15*s**4 + 6*s**5

def _bezier_quad(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, t: float) -> np.ndarray:
    """Квадратичный Безье (две контрольные точки)"""
    return (1-t)**2 * p0 + 2*(1-t)*t * p1 + t**2 * p2



def human_moveTo(
    x: int,
    y: int,
    *,
    speed: Speed = Speed.MEDIUM,
    jitter_range: Tuple[int, int] = (0, 0),
    samples_per_sec: int = 250,  # увеличено до 250 для более плавных движений
    target_tolerance: float = 10.0,  # увеличено для меньших коррекций
    fitts_W: float = 12.0,
    hold_button: bool = False,  # зажать левую кнопку мыши при перемещении
    interpolate: bool = True,  # линейная интерполяция между точками (для более гладких линий в Paint)
    debug: bool = False
) -> None:
    """
    Переместить курсор к (x,y) "человечески".
    Параметры:
      x, y               - целевые координаты (экранные, int).
      speed              - Speed.SLOW | Speed.MEDIUM | Speed.FAST (enum).
      jitter_range       - (max_x_jitter_px, max_y_jitter_px): финальный рандомный разброс цели.
      samples_per_sec    - сколько точек в секунду генерировать (плавность).
      target_tolerance   - когда считать, что мы попали (px) — при необходимости делать коррекции.
      fitts_W            - "ширина" цели для Fitts' law (px). Используется в расчёте времени.
      hold_button        - если True, зажимает левую кнопку мыши во время перемещения.
      interpolate        - если True, добавляет линейную интерполяцию между точками для более гладких линий.
      debug              - если True, печатает некоторые промежуточные данные.
    Поведение:
      - случайная небольшая боковая кривизна пути (контрольная точка без сильного отклонения),
      - базовый профиль движения по minimum-jerk,
      - сигнал-зависимый гауссов шум на каждом шаге (sigma ~ k * локальная скорость),
      - после основной траектории — микрокоррекции, если осталось расстояние > target_tolerance.
      - если hold_button=True, кнопка зажимается перед перемещением и отпускается после.
    """
    # старт
    sx, sy = pyautogui.position()
    start = np.array([sx, sy], dtype=float)
    end = np.array([x, y], dtype=float)

    # если нужно зажать кнопку — зажимаем перед началом движения
    if hold_button:
        pyautogui.mouseDown(button='left')
        if debug:
            print("Левая кнопка мыши зажата")
        time.sleep(0.05)  # небольшая пауза после нажатия

    # применить случайный окончательный джиттер (параметр: jitter_range)
    jx = random.uniform(-abs(jitter_range[0]), abs(jitter_range[0]))
    jy = random.uniform(-abs(jitter_range[1]), abs(jitter_range[1]))
    end = end + np.array([jx, jy], dtype=float)

    # ограничи цель размерами экрана:
    screen_w, screen_h = pyautogui.size()
    end[0] = max(0, min(screen_w - 1, end[0]))
    end[1] = max(0, min(screen_h - 1, end[1]))

    # расстояние
    D = float(np.linalg.norm(end - start))
    if D < 1.0:
        if debug:
            print("Already at target (or extremely close).")
        pyautogui.moveTo(int(end[0]), int(end[1]))
        return

    # --- Определение времени движения (movement time) по Fitts' law + рандомизация по speed ---
    # Fitts' law: MT = a + b * log2(D/W + 1)
    # подбираем базовые коэффициенты для скоростей (в секундах) - уменьшены для быстрого движения
    speed_params = {
        Speed.SLOW: (0.08, 0.25),   # a, b (было 0.12, 0.48)
        Speed.MEDIUM: (0.05, 0.18), # было (0.08, 0.38)
        Speed.FAST: (0.03, 0.12)    # было (0.04, 0.28)
    }
    a, b = speed_params[speed]
    MT = a + b * math.log2(D / max(1.0, fitts_W) + 1.0)
    # уменьшена рандомизация для более предсказуемого времени
    mt_jitter_factor = {"slow": 0.25, "medium": 0.15, "fast": 0.12}[speed.value]
    MT = MT * random.uniform(1.0 - mt_jitter_factor, 1.0 + mt_jitter_factor)
    MT = max(0.015, MT)  # защита от нулевых/отрицательных

    if debug:
        print(f"Distance: {D:.1f}px, Movement time MT: {MT:.3f}s, final jitter: ({jx:.1f},{jy:.1f})")

    # --- Генерация трассы: используем квадратичный Безье для небольшой естественной кривизны ---
    # контрольная точка примерно в середине + небольшой перпендикулярный сдвиг
    mid = (start + end) / 2.0
    # вектор от start до end
    v = end - start
    # перпендикуляр единичный
    perp = np.array([-v[1], v[0]])
    if np.linalg.norm(perp) > 0:
        perp = perp / np.linalg.norm(perp)
    # амплитуда кривизны пропорциональна расстоянию и рандома (не более ~ D*0.18)
    max_curve = D * random.uniform(-0.12, 0.12)
    control = mid + perp * max_curve

    # выбор числа сэмплов - оптимизировано
    n_samples = max(3, min(int(samples_per_sec * MT), 30))  # ограничиваем максимум 30 точками
    dt = MT / n_samples

    # При зажатии кнопки (рисование в Paint) увеличиваем количество точек для более гладкого рисования
    if hold_button:
        n_samples = max(6, min(int(samples_per_sec * MT * 2), 60))  # в 2 раза больше точек
        dt = MT / n_samples

    # парамет для шумовой константы: уменьшен для меньшей рывковости
    speed_noise_k = {"slow": 0.3, "medium": 0.5, "fast": 0.8}[speed.value]
    # base noise scale in px per (px/s) - уменьшен
    noise_scale_base = 0.0012  # было 0.0025

    # генерируем путь: каждый s от 0..1 -> применяем minimum-jerk шкалу для времени -> берем Безье точку
    times: List[float] = []
    points: List[np.ndarray] = []
    for i in range(n_samples + 1):
        t_raw = i / n_samples  # линейный парамет
        s = _minimum_jerk_scale(t_raw)  # скоростная шкала
        # для плавной кривизны используем s как параметр Безье
        pt = _bezier_quad(start, control, end, s)
        times.append(t_raw * MT)
        points.append(pt)

    # теперь добавим сигнал-зависимый шум: sigma ~ k * v_local
    noisy_points: List[np.ndarray] = []
    prev_pt = points[0]
    # чтобы вычислить локальную скорость (px/s) используем finite diff over dt*scale
    for i in range(len(points)):
        pt = points[i]
        if i == 0:
            v_local = np.linalg.norm(points[i+1] - points[i]) / max(1e-6, dt)
        else:
            v_local = np.linalg.norm(points[i] - points[i-1]) / max(1e-6, dt)

        sigma = noise_scale_base * v_local * speed_noise_k
        # шум по x и y (независимый)
        noise = np.random.normal(loc=0.0, scale=sigma, size=2)
        noisy_pt = pt + noise
        noisy_points.append(noisy_pt)
        prev_pt = pt

    # Если включена интерполяция и зажата кнопка - добавляем промежуточные точки между основными точками
    if interpolate and hold_button and len(noisy_points) > 1:
        interpolated_points = []
        for i in range(len(noisy_points) - 1):
            p1 = noisy_points[i]
            p2 = noisy_points[i + 1]
            interpolated_points.append(p1)
            
            # Добавляем 1-2 промежуточные точки между текущей и следующей
            dist = np.linalg.norm(p2 - p1)
            if dist > 1.0:  # если расстояние достаточно большое
                n_interp = int(dist)  # количество промежуточных точек
                for j in range(1, min(n_interp, 3)):  # макс 2 промежуточные точки
                    t = j / min(n_interp, 3)
                    interp_pt = p1 + t * (p2 - p1)
                    interpolated_points.append(interp_pt)
        
        interpolated_points.append(noisy_points[-1])  # добавляем последнюю точку
        noisy_points = interpolated_points

    # --- Прогон: перемещаемся по noisy_points с паузами dt ---
    start_time = time.perf_counter()
    prev_tx, prev_ty = int(round(noisy_points[0][0])), int(round(noisy_points[0][1]))
    
    for idx, pt in enumerate(noisy_points):
        tx = int(round(pt[0]))
        ty = int(round(pt[1]))
        # clamp
        tx = max(0, min(screen_w - 1, tx))
        ty = max(0, min(screen_h - 1, ty))
        
        try:
            if hold_button:
                # При зажатой кнопке используем drag вместо moveTo
                # drag работает относительно текущей позиции
                dx = tx - prev_tx
                dy = ty - prev_ty
                if dx != 0 or dy != 0:  # только если есть смещение
                    pyautogui.drag(dx, dy, duration=0, _pause=False)
                prev_tx, prev_ty = tx, ty
            else:
                # Обычное перемещение без кнопки
                pyautogui.moveTo(tx, ty, _pause=False)
        except pyautogui.FailSafeException:
            # пользователь дернул мышь в угол — безопасный выход
            if debug:
                print("FailSafe triggered — aborting human_move.")
            # если была нажата кнопка - отпускаем её
            if hold_button:
                pyautogui.mouseUp(button='left')
            return
        
        # точное время ожидания следующего фрейма
        # при интерполяции с зажатой кнопкой уменьшаем паузу для более плавного рисования
        if interpolate and hold_button:
            sleep_time = dt * 0.3  # на 70% быстрее прогон через интерполированные точки
        else:
            sleep_time = dt
            
        if idx < len(noisy_points) - 1:  # не ждём после последней точки
            target_time = start_time + (idx + 1) * sleep_time
            now = time.perf_counter()
            sleep_for = target_time - now
            if sleep_for > 0:
                time.sleep(sleep_for)

    # --- Микрокоррекции: если осталось отклонение > target_tolerance, делаем 1-2 быстрых коррекции ---
    final_pos = np.array(pyautogui.position(), dtype=float)
    dist_left = np.linalg.norm(end - final_pos)
    if debug:
        print(f"After main move: dist_left = {dist_left:.2f}px")

    correction_attempts = 0
    while dist_left > target_tolerance and correction_attempts < 2:  # было 3, теперь 2
        # план маленькой корректировки: короткий MT proportional to dist_left
        corr_MT = max(0.01, 0.04 * (dist_left / max(1.0, fitts_W)))  # было 0.015, 0.07
        corr_samples = max(2, int(samples_per_sec * corr_MT * 0.5))  # меньше точек
        # целевая точка с небольшим джиттером (могут быть мелкие промахи)
        tiny_jx = random.uniform(-0.8, 0.8)  # было -1.2, 1.2
        tiny_jy = random.uniform(-0.8, 0.8)
        corr_end = end + np.array([tiny_jx, tiny_jy])

        corr_points = []
        for i in range(corr_samples + 1):
            s = _minimum_jerk_scale(i / corr_samples)
            pt = (1 - s) * final_pos + s * corr_end
            # меньший шум
            v_local = np.linalg.norm(pt - final_pos) / max(1e-6, corr_MT / corr_samples)
            sigma = noise_scale_base * v_local * (0.5 * speed_noise_k)  # было 0.9
            noise = np.random.normal(scale=sigma, size=2)
            corr_points.append(pt + noise)
            final_pos = pt

        corr_dt = corr_MT / max(1, corr_samples)
        for p in corr_points:
            tx = int(round(p[0])); ty = int(round(p[1]))
            tx = max(0, min(screen_w - 1, tx))
            ty = max(0, min(screen_h - 1, ty))
            try:
                pyautogui.moveTo(tx, ty, _pause=False)
            except pyautogui.FailSafeException:
                if debug:
                    print("FailSafe triggered during correction — aborting.")
                return
            time.sleep(corr_dt)

        final_pos = np.array(pyautogui.position(), dtype=float)
        dist_left = np.linalg.norm(end - final_pos)
        correction_attempts += 1
        if debug:
            print(f"Correction {correction_attempts}: dist_left = {dist_left:.2f}px")

    # финально поставим курсор точно на целевую точку (мелкая точная установка)
    try:
        pyautogui.moveTo(int(round(end[0])), int(round(end[1])), _pause=False)
    except pyautogui.FailSafeException:
        if debug:
            print("FailSafe on final move.")
    
    # если кнопка была зажата — отпускаем её в конце
    if hold_button:
        time.sleep(0.05)  # небольшая пауза перед отпусканием
        pyautogui.mouseUp(button='left')
        if debug:
            print("Левая кнопка мыши отпущена")


# Пример использования:
# human_moveTo(800, 400, speed=Speed.MEDIUM, jitter_range=(2,2), debug=True)

if __name__ == "__main__":
    # Тестовое перемещение
    human_moveTo(400, 400, jitter_range=(15,40), hold_button=True)