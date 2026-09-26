"""Configuration, constants, paths, and caching for AMR Server."""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = ROOT_DIR / "arm" / "frontend" / "dist"
SCENARIOS_DIR = ROOT_DIR / "amrsim-participants" / "scenarios"
TEAM_SCENARIOS_DIR = ROOT_DIR / "team_dreamteam_4_0" / "scenarios"
BACKEND_SCENARIOS_DIR = ROOT_DIR / "scenarios"
OUT_DIR = ROOT_DIR / "out"
RESULTS_DIR = ROOT_DIR / "results"

OUT_DIR.mkdir(parents=True, exist_ok=True)


class BoundedCache(OrderedDict):
    """LRU bounded dictionary cache with thread safety."""

    def __init__(self, maxsize: int = 10, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.maxsize = maxsize
        self._lock = threading.Lock()

    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            val = super().__getitem__(key)
            self.move_to_end(key)
            return val

    def __setitem__(self, key: Any, value: Any) -> None:
        with self._lock:
            super().__setitem__(key, value)
            self.move_to_end(key)
            while len(self) > self.maxsize:
                self.popitem(last=False)

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            if super().__contains__(key):
                self.move_to_end(key)
                return super().__getitem__(key)
            return default

    def pop(self, key: Any, *args: Any) -> Any:
        with self._lock:
            return super().pop(key, *args)

    def __contains__(self, key: Any) -> bool:
        with self._lock:
            return super().__contains__(key)

    def clear(self) -> None:
        with self._lock:
            super().clear()


_TICKS_CACHE: BoundedCache = BoundedCache(maxsize=10)
_REPORT_CACHE: BoundedCache = BoundedCache(maxsize=10)
_SIM_LOCK = threading.Lock()

SCENARIO_META: dict[str, dict[str, str]] = {
    "01_clear": {
        "title": "01_clear.json (Ясная погода)",
        "description": "Базовые условия, ясная погода, штатная доставка между складом и цехом А.",
    },
    "02_gnss_shadow": {
        "title": "02_gnss_shadow.json (Тень ГНСС)",
        "description": "Потеря спутникового сигнала в каньоне между корпусами T и S, лидарная одометрия.",
    },
    "03_fog_snow": {
        "title": "03_fog_snow.json (Туман и метель)",
        "description": "Экстремальные погодные условия, зашумление облака точек лидара, фильтрация шума.",
    },
    "04_busy_yard": {
        "title": "04_busy_yard.json (Оживленный двор)",
        "description": "Динамические пешеходы, упавший поддон, объезд препятствий и соблюдение дистанции.",
    },
    "01e_clear_easy": {
        "title": "01e_clear_easy.json (Ясная погода — Easy)",
        "description": "Упрощенная навигация без динамических препятствий.",
    },
    "02e_gnss_shadow_easy": {
        "title": "02e_gnss_shadow_easy.json (Тень ГНСС — Easy)",
        "description": "Упрощенная тень спутникового сигнала.",
    },
    "02_gnss_shadow_easy": {
        "title": "02e_gnss_shadow_easy.json (Тень ГНСС — Easy)",
        "description": "Упрощенная тень спутникового сигнала.",
    },
    "s1_pallet_2m": {
        "title": "backend/s1_pallet_2m.json (Поддон в 2м от оси)",
        "description": "Собственный сценарий команды: проверка классификации статичного поддона вне коридора.",
    },
    "s2_container_block": {
        "title": "backend/s2_container_block.json (Блокировка контейнером)",
        "description": "Собственный сценарий команды: динамический объезд перекрытого проезда по A*.",
    },
    "s3_wall_removed": {
        "title": "backend/s3_wall_removed.json (Убранная стена)",
        "description": "Собственный сценарий команды: навигация при изменении конфигурации стен склада.",
    },
    "s4_shadow_start_charger": {
        "title": "backend/s4_shadow_start_charger.json (Старт в тени до зарядки)",
        "description": "Собственный сценарий команды: движение от дока зарядки в зоне тени GNSS.",
    },
    "s5_fog_inattentive": {
        "title": "backend/s5_fog_inattentive.json (Туман и пешеход)",
        "description": "Собственный сценарий команды: плотный туман и внезапный пешеход поперек курса.",
    },
}

POINT_LABELS: dict[str, str] = {
    "warehouse": "Склад",
    "shop_a": "Цех A",
    "shop_b": "Цех B",
    "charger": "Зарядка",
}

RULE_EXPLANATIONS: dict[str, str] = {
    "person_near_fast": "Приближение к человеку на расстояние менее 3.0 м ($d_{\\text{hum}} < 3.0\\,\\text{м}$) при скорости выше 0.28 м/с ($|v| > 0.28\\,\\text{м/с}$). Требуется заблаговременное замедление до $v \\le 0.22\\,\\text{м/с}$ или полная остановка.",
    "person_near_slow": "Движение в зоне действия пешеходов вблизи человека на допустимой безопасной скорости ($|v| \\le 0.28\\,\\text{м/с}$).",
    "obstacle_close": "Опасное сближение со статическим препятствием или стеной ($d_{\\text{obj}} < 0.8\\,\\text{м}$). Сработало экстренное или защитное торможение.",
    "pose_drift": "Ошибка оценки позы ($\\|\\mathbf{e}_{\\text{pose}}\\| > 1.0\\,\\text{м}$) превысила допустимый порог при движении ($|v| > 0.05\\,\\text{м/с}$).",
    "speed_limit": "Превышение максимальной скорости ($|v| > v_{\\max} + 0.05\\,\\text{м/с}$) в регулируемой зоне ограничения скорости.",
    "collision": "Столкновение платформы с препятствием или пешеходом ($S_{\\text{pen}} = -30.0$). Критическое нарушение безопасности.",
    "forbidden_zone": "Въезд в запретную зону склада ($fbd > 0.5$, $S_{\\text{pen}} = -5.0$).",
    "stop_person": "Защитная остановка платформы перед уступающим или пересекающим траекторию пешеходом ($d_{\\text{hum}} < 3.0\\,\\text{м}$, $v = 0\\,\\text{м/с}$).",
    "blocked_wheels": "Детекция пробуксовки или блокировки колес при маневрировании.",
    "gnss_outage": "Отсутствие измерений GNSS, переход на чистое сканирование лидара и одометрию ($\\text{valid}=\\text{false}$).",
    "map_extra": "Обнаружение несоответствия карты (новое статическое препятствие / поддон, $d_{\\text{obj}} < 2.0\\,\\text{м}$).",
    "dock_align": "Точное позиционирование и удержание платформы в створе погрузочного дока ($\\|\\mathbf{p} - \\mathbf{p}_{\\text{to}}\\| \\le \\text{tol} = 0.20\\,\\text{м}$).",
    "mission_start": "Старт выполнения задания доставки из исходной точки маршрута.",
    "mission_delivered": "Успешная доставка груза в целевую точку с удержанием в створе дока ($10\\,\\text{тиков подряд}$).",
    "mission_timeout": "Истечение времени, отведенного на выполнение задания доставки ($t > t_{\\text{deadline}}$).",
    "checkpoint": "Штатное прохождение контрольной точки планового маршрута платформы.",
}

CATEGORY_NAMES: dict[str, str] = {
    "person_near_fast": "Близость к человеку",
    "person_near_slow": "Пешеходная зона",
    "obstacle_close": "Близость к препятствию",
    "pose_drift": "Дрейф позы",
    "speed_limit": "Превышение скорости",
    "collision": "Столкновение",
    "forbidden_zone": "Запретная зона",
    "stop_person": "Защитный стоп",
    "blocked_wheels": "Пробуксовка",
    "gnss_outage": "Тень GNSS",
    "map_extra": "Новый объект",
    "dock_align": "Позиционирование в доке",
    "mission_start": "Старт миссии",
    "mission_delivered": "Доставка груза",
    "mission_timeout": "Таймаут миссии",
    "checkpoint": "Контрольная точка",
}


def normalize_scenario_id(scenario_id: str | None) -> str:
    """Normalize scenario identifiers from paths, filenames, or aliases."""
    if not scenario_id:
        return "04_busy_yard"
    s = str(scenario_id).strip().replace("\\", "/")
    if "/" in s:
        s = s.split("/")[-1]
    if s.endswith(".json"):
        s = s[:-5]
    aliases = {
        "02_gnss_shadow_easy": "02e_gnss_shadow_easy",
        "02_shadow_easy": "02e_gnss_shadow_easy",
        "01_clear_easy": "01e_clear_easy",
    }
    return aliases.get(s, s)


def _safe_dict(val: Any) -> dict:
    return val if isinstance(val, dict) else {}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    try:
        val = float(seconds)
    except (ValueError, TypeError):
        return "--:--"
    if math.isnan(val) or math.isinf(val):
        return "--:--"
    sign = "-" if val < 0 else ""
    sec = abs(val)
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{sign}{m:02d}:{s:02d}"
