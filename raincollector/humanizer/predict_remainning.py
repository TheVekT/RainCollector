
"""
Usage:
  python predict_remaining.py --stats stats.json --scrap 20 --users 210 --now 2025-10-30T19:00:00
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

# ---------------- helpers ----------------
def _parse_hour(timestr: Optional[str]) -> int:
    """
    Возвращает час 0..23.
    Если timestr отсутствует или не парсится — возвращаем текущее UTC-час (не deprecated).
    """
    if not timestr:
        return datetime.now(timezone.utc).hour
    # try iso
    try:
        # fromisoformat может вернуть naive datetime; take hour directly
        dt = datetime.fromisoformat(timestr)
        # if dt is naive treat as local-ish, but we only need .hour
        return dt.hour
    except Exception:
        pass
    # try common format
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(timestr, fmt).hour
        except Exception:
            pass
    # fallback to current UTC hour (avoids using deprecated utcnow)
    return datetime.now(timezone.utc).hour

def _time_bucket_for_hour(h: int, time_buckets: Optional[Dict[str, tuple]] = None) -> str:
    TB = {
        "morning": (6, 11),
        "day":     (12, 17),
        "evening": (18, 22),
        "night":   (23, 5),
    }
    buckets = time_buckets or TB
    for name, (start, end) in buckets.items():
        if start <= end:
            if start <= h <= end:
                return name
        else:
            # wrap-around bucket (e.g. 23..5)
            if h >= start or h <= end:
                return name
    return "unknown"

def _scrap_bin_label(scrap: int, bin_size: int) -> str:
    low = (scrap // bin_size) * bin_size
    high = low + bin_size - 1
    return f"{low}-{high}"

def _parse_bin_label(label: str) -> Optional[Tuple[int,int]]:
    """Парсит 'low-high' -> (low, high) или None."""
    try:
        low_s, high_s = label.split("-")
        return int(low_s), int(high_s)
    except Exception:
        return None

# ---------------- core ----------------
def load_stats(path: str = "stats.json") -> Dict[str,Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _expected_from_stats(stats: Dict[str,Any], scrap: int, hour: Optional[int]) -> float:
    """
    Возвращает ожидаемое финальное число пользователей для данного scrap и часа.
    Если scrap попадает за пределы имеющихся бин-диапазонов, используем максимальный (или минимальный) бин.
    """
    bin_size = int(stats.get("bin_size", 10))
    by_bin = stats.get("by_bin", {})
    # prefer exact calculated bin label first
    wanted_label = _scrap_bin_label(scrap, bin_size)
    if wanted_label in by_bin:
        entry = by_bin[wanted_label]
        if hour is not None:
            bucket = _time_bucket_for_hour(hour)
            if bucket in entry:
                return float(entry[bucket])
        if "median_all" in entry:
            return float(entry["median_all"])

    # if exact label missing, examine available bins
    parsed_bins: List[Tuple[int,int,str]] = []
    for label in by_bin.keys():
        parsed = _parse_bin_label(label)
        if parsed is None:
            continue
        low, high = parsed
        parsed_bins.append((low, high, label))
    if not parsed_bins:
        # nothing useful -> global median fallback
        return float(stats.get("global_median", 1.0))

    # if scrap is beyond max or below min, map to extreme bin
    max_bin = max(parsed_bins, key=lambda x: x[1])
    min_bin = min(parsed_bins, key=lambda x: x[0])
    if scrap > max_bin[1]:
        label = max_bin[2]
        entry = by_bin.get(label, {})
        if hour is not None:
            bucket = _time_bucket_for_hour(hour)
            if bucket in entry:
                return float(entry[bucket])
        return float(entry.get("median_all", stats.get("global_median", 1.0)))
    if scrap < min_bin[0]:
        label = min_bin[2]
        entry = by_bin.get(label, {})
        if hour is not None:
            bucket = _time_bucket_for_hour(hour)
            if bucket in entry:
                return float(entry[bucket])
        return float(entry.get("median_all", stats.get("global_median", 1.0)))

    # scrap is within global min..max but exact label wasn't present: try to find bin which contains scrap
    for low, high, label in parsed_bins:
        if low <= scrap <= high:
            entry = by_bin.get(label, {})
            if hour is not None:
                bucket = _time_bucket_for_hour(hour)
                if bucket in entry:
                    return float(entry[bucket])
            return float(entry.get("median_all", stats.get("global_median", 1.0)))

    # fallback global median
    return float(stats.get("global_median", 1.0))

def predict_remaining_from_stats(stats: Dict[str,Any],
                                 scrap: int,
                                 current_users: int,
                                 now_iso: Optional[str] = None) -> int:
    """
    Возвращает remaining seconds (int).
    """
    hour = _parse_hour(now_iso) if now_iso else datetime.now(timezone.utc).hour
    expected = _expected_from_stats(stats, scrap, hour)
    expected = max(1.0, expected)
    progress = float(current_users) / expected
    if progress <= 0.0:
        elapsed = 0.0
    else:
        p = max(0.0, min(1.0, progress))
        T = float(stats.get("raid_duration_s", 180.0))
        alpha = float(stats.get("alpha", 0.6))
        elapsed = T * (p ** (1.0 / alpha))
    remaining = max(0.0, float(stats.get("raid_duration_s", 180.0)) - elapsed)
    return int(round(remaining))