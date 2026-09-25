"""Контроллер автономной мобильной платформы для кейса 'Безопасный маршрут'.

Строго соответствует схеме AMR-1.0, правилам изоляции и порогам оценки.
Используются только стандартная библиотека и numpy.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from .geom import box_segs, raycast
    from .localize import Localizer
    from .perceive import Perception
    from .route import RouteFollower
    from .safety import SafetyGovernor
except ImportError:
    from geom import box_segs, raycast
    from localize import Localizer
    from perceive import Perception
    from route import RouteFollower
    from safety import SafetyGovernor


class Controller:
    """Интегрированный контроллер AMR-платформы.

    Порядок выполнения в step(obs):
    1. Прогноз позы по одометрии и IMU.
    2. Сопоставление сканов со стенами, стробирование невязки GNSS, привязка к доку.
    3. Кластеризация и отслеживание препятствий в чистом базисе одометрии.
    4. Следование по миссии, боковой объезд или планирование пути A*.
    5. Чистое преследование, ограничения скоростных зон, прогнозный модуль безопасности.
    6. Определение статуса по измеренной скорости одометрии (движение >= 0.05 м/с).
    7. Фильтрация среднего значения на выходе в pose_est.
    """

    def __init__(self, map_: Dict[str, Any], config: Dict[str, Any], initial_pose: List[float]):
        self.map = map_
        self.config = config
        self.dt = float(config.get("dt", 0.1))

        # Динамические ограничения платформы
        rb = config.get("robot", {})
        self.v_top = float(rb.get("v_max", 1.39))

        # Углы лучей лидара
        lid = config.get("lidar", {})
        beams = int(lid.get("beams", 360))
        amin = float(lid.get("angle_min_deg", 0.0))
        ainc = float(lid.get("angle_increment_deg", 1.0))
        self.rel_angles = np.radians(amin + ainc * np.arange(beams))

        # Отрезки стен зданий
        self.building_segs = box_segs(map_.get("buildings", []))
        # Столбы - это мелкие полигоны карты (максимальная сторона < 1 м), используемые
        # локализатором как продольные ориентиры.
        self.pole_centers = self._extract_pole_centers(map_.get("buildings", []))

        # Подсистемы
        self.localizer = self._make_localizer(initial_pose)
        self.perception = Perception(dt=self.dt)
        self.route = RouteFollower(map_dict=map_, config=config)
        self.safety = SafetyGovernor(v_top=self.v_top, dt=self.dt)

        # Зоны
        self.zones = [
            (np.asarray(z["polygon"], dtype=float), float(z["v_max"]))
            for z in map_.get("zones", [])
            if z.get("type") == "speed_limit" or "v_max" in z
        ]

        # Отслеживание миссии и прибытия
        self.current_mission_id: Optional[str] = None
        self.arrived: bool = False
        self.visited_from: bool = False
        self.truth_pose: Optional[List[float]] = None
        self.last_recover_t: float = -1e9

    @staticmethod
    def _extract_pole_centers(buildings: Any) -> np.ndarray:
        """Собрать центры мелких полигонов карты (столбы, plan/02:68).

        Полигон считается столбом, когда его наибольшая сторона короче 1 м.
        Возвращает массив float (N, 2), пустой, если таких полигонов нет.
        """
        centers: List[List[float]] = []
        for b in buildings or []:
            poly = b.get("polygon") if isinstance(b, dict) else b
            if poly is None or len(poly) < 3:
                continue
            try:
                pts = np.asarray(poly, dtype=float)
            except (TypeError, ValueError):
                continue
            if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] < 2:
                continue
            closed = np.vstack([pts[:, :2], pts[:1, :2]])
            sides = np.hypot(np.diff(closed[:, 0]), np.diff(closed[:, 1]))
            if sides.size == 0 or float(sides.max()) >= 1.0:
                continue
            centers.append([float(pts[:, 0].mean()), float(pts[:, 1].mean())])
        if not centers:
            return np.empty((0, 2), dtype=float)
        return np.asarray(centers, dtype=float)

    def _make_localizer(self, initial_pose: List[float]) -> "Localizer":
        """Собрать Localizer с ориентирами карты (столбы, plan/02:68)."""
        return Localizer(
            initial_pose=initial_pose,
            building_segs=self.building_segs,
            pole_centers=self.pole_centers,
        )

    def set_truth(self, pose: List[float]) -> None:
        """Хук истинной позы только для локального бенчмаркинга --cheat."""
        self.truth_pose = [float(p) for p in pose]

    @staticmethod
    def _track_world_xy(
        trk: Any,
        pose: Tuple[float, float, float],
        odom_pose: Tuple[float, float, float],
    ) -> Tuple[float, float]:
        """Преобразовать центроид трека из чистого базиса одометрии в мировой базис."""
        cos_o, sin_o = math.cos(odom_pose[2]), math.sin(odom_pose[2])
        cos_w, sin_w = math.cos(pose[2]), math.sin(pose[2])
        dx_o = trk.ox - odom_pose[0]
        dy_o = trk.oy - odom_pose[1]
        # Базис одометрии -> базис робота
        rx = cos_o * dx_o + sin_o * dy_o
        ry = -sin_o * dx_o + cos_o * dy_o
        # Базис робота -> глобальный базис
        return (pose[0] + cos_w * rx - sin_w * ry, pose[1] + sin_w * rx + cos_w * ry)

    def _active_tracks(self) -> List[Any]:
        """Вернуть только подтвержденные треки для безопасности и слоя препятствий.

        Трек подтверждается, когда его история ``seen`` содержит два подряд
        попадания (1,1), и подтвержденный трек остается подтвержденным, пока
        движется по инерции - пропуск в тумане не должен снимать торможение
        (plan/03:20, plan/02:143-145).
        """
        return list(self.perception.active_tracks)

    def step(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнить один цикл управления AMR-платформой."""
        # 1. Прогноз позы по одометрии и IMU
        odom = obs["odom"]
        imu = obs["imu"]
        dx_odom = float(odom["dx"])
        dy_odom = float(odom["dy"])
        dth_odom = float(odom["dtheta"])
        imu_heading = float(imu["heading"])
        imu_yaw_rate = float(imu["yaw_rate"])

        self.localizer.predict(dx_odom, dy_odom, dth_odom, imu_heading, imu_yaw_rate, self.dt)

        # 2. Сопоставление сканов лидара со стенами карты
        ranges = np.asarray(obs["lidar"]["ranges"], dtype=float)
        rel_angles = self.rel_angles
        exp_ranges = raycast(
            self.localizer.x, self.localizer.y, self.localizer.th + rel_angles, self.building_segs
        )
        is_fog = self.localizer.detect_fog(ranges, expected_ranges=exp_ranges)

        # Активные отрезки зданий (с исключением снесенных стен по данным распознавания)
        active_segs = self.building_segs
        if self.perception.removed_segment_ids:
            mask = np.ones(len(self.building_segs), dtype=bool)
            for sid in self.perception.removed_segment_ids:
                if 0 <= sid < len(self.building_segs):
                    mask[sid] = False
            active_segs = self.building_segs[mask]

        self.localizer.update_scan(ranges, rel_angles, active_segs, is_fog=is_fog)

        # 2b. Восстановление потерянной позы: неподвижная платформа повторно ищет карту.
        # try_recover() выполняется только при полной остановке платформы, поэтому флаг
        # stopped передается явно. Не более одной попытки в секунду.
        v_odom = dx_odom / self.dt
        if self.localizer.is_lost:
            now_t = float(obs.get("t", 0.0))
            if now_t - self.last_recover_t >= 1.0:
                self.last_recover_t = now_t
                recover = getattr(self.localizer, "try_recover", None)
                if callable(recover):
                    recover(
                        ranges=ranges,
                        rel_angles=rel_angles,
                        segs=active_segs,
                        stopped=(abs(v_odom) < 0.04),
                    )

        # 3. Обновление GNSS со стробированием невязки
        gnss = obs.get("gnss", {})
        raw_x = gnss.get("x")
        raw_y = gnss.get("y")
        gnss_valid = bool(gnss.get("valid", False)) and raw_x is not None and raw_y is not None
        gnss_x = float(raw_x) if raw_x is not None else 0.0
        gnss_y = float(raw_y) if raw_y is not None else 0.0
        raw_hdop = gnss.get("hdop")
        gnss_hdop = float(raw_hdop) if raw_hdop is not None else 99.0
        self.localizer.update_gnss(gnss_x, gnss_y, gnss_valid, gnss_hdop)

        # Переопределение истинной позы (ground truth), если включено
        if self.truth_pose is not None:
            self.localizer.x, self.localizer.y, self.localizer.th = self.truth_pose
            self.localizer.var_along = 0.0
            self.localizer.var_cross = 0.0
            self.localizer.var_th = 0.0

        pose = self.localizer.pose
        odom_pose = self.localizer.odom_pose
        w_odom = dth_odom / self.dt

        # 4. Управление миссией и привязка к доку
        mission = obs.get("mission")
        if mission is not None:
            mid = mission.get("id")
            if mid != self.current_mission_id:
                self.current_mission_id = mid
                self.arrived = False
                self.visited_from = False

            # Проверка близости к точке погрузки (фильтр в пределах 1.5 м во время миссии)
            from_key = mission.get("from")
            if isinstance(from_key, str) and "points" in self.map:
                pt_info = self.map["points"].get(from_key, {})
                fx, fy = float(pt_info.get("x", 0.0)), float(pt_info.get("y", 0.0))
                d_from = math.hypot(pose[0] - fx, pose[1] - fy)
                if d_from < 1.5:
                    self.visited_from = True
            elif isinstance(from_key, (list, tuple)) and len(from_key) >= 2:
                d_from = math.hypot(pose[0] - from_key[0], pose[1] - from_key[1])
                if d_from < 1.5:
                    self.visited_from = True

            # Привязка к доку возле целевой точки
            goal_pt = mission.get("goal")
            if goal_pt is not None and len(goal_pt) >= 3 and not self.truth_pose:
                self.localizer.dock_snap(ranges, rel_angles, goal_pt, active_segs)
                pose = self.localizer.pose

        # Если уже прибыл и удерживается статус прибытия
        if self.arrived:
            return {
                "v": 0.0,
                "w": 0.0,
                "status": "arrived",
                "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
                "note": "dock",
            }

        # 5. Распознавание: отслеживание динамических и статических препятствий в чистом базисе одометрии
        self.perception.step(
            ranges=ranges,
            rel_angles=rel_angles,
            pose=pose,
            odom_pose=odom_pose,
            map_segs=self.building_segs,
            sigma_pose=self.localizer.sigma_cross,
            is_fog=is_fog,
            v_odom=v_odom,
            scan_inliers=self.localizer.scan_inliers,
        )

        # Только подтвержденные треки передаются в модуль безопасности и слой препятствий
        # маршрута. Одиночный снежный отклик не повторяется в одной точке мира от такта к такту,
        # поэтому не должен считаться ложным пешеходом и останавливать миссию.
        active_tracks = self._active_tracks()

        # Извлечение подтвержденных статических препятствий для планировщика маршрута
        static_obs: List[Tuple[float, float, float]] = []
        confirmed_xy: List[Tuple[float, float]] = []
        for trk in active_tracks:
            if trk.is_pedestrian or trk.is_unknown:
                continue
            wx, wy = self._track_world_xy(trk, pose, odom_pose)
            confirmed_xy.append((wx, wy))
            if trk.is_static_object and not trk.is_wall:
                r_obs = max(0.4, 0.5 * min(2.0, trk.length))
                static_obs.append((wx, wy, r_obs))

        # Расхождения карты (map_extra / wall_extra) также передаются в слой препятствий маршрута,
        # иначе неразмеченный участок проходится в лоб. Дополнительный слой принимается только для
        # подтвержденных треков, исключая перестроение маршрута по фантомным стенам.
        for ex, ey, er in self.perception.get_extra_obstacles():
            if not any(math.hypot(ex - cx, ey - cy) < 0.35 for cx, cy in confirmed_xy):
                continue
            if any(math.hypot(ex - sx, ey - sy) < 0.35 for sx, sy, _ in static_obs):
                continue
            static_obs.append((float(ex), float(ey), float(er)))

        # 6. Шаг следования по маршруту
        route_cmd = self.route.step(
            pose=pose,
            mission=mission,
            obstacles=static_obs,
            current_time=float(obs.get("t", 0.0)),
        )

        v_cand = float(route_cmd.get("v", 0.0))
        w_cand = float(route_cmd.get("w", 0.0))
        rem_dist = float(route_cmd.get("remaining_dist", 99.0))
        route_note = route_cmd.get("note") or ""

        # Ограничение скорости при потере ориентации: ограничение применяется на каждом такте,
        # lost_speed_limit включает все ступени скорости: 0.4 (высокая поперечная или угловая погрешность),
        # 0.6 (высокая продольная погрешность), 0.0 (потеря), 1.39 (номинальный режим).
        lost_cap = float(getattr(self.localizer, "lost_speed_limit", 1.39))
        if lost_cap < v_cand:
            v_cand = lost_cap

        # Проверка порога прибытия в конечный док
        if mission is not None and len(self.route.active_path) >= 2:
            terminal_pt = self.route.active_path[-1]
            dist_to_dock = math.hypot(pose[0] - terminal_pt[0], pose[1] - terminal_pt[1])
            is_route_arrived = bool(
                route_cmd.get("arrived", False) or route_cmd.get("status") == "arrived"
            )
            if (
                (dist_to_dock <= 0.10 or is_route_arrived)
                and abs(v_odom) < 0.04
                and self.visited_from
            ):
                self.arrived = True
                return {
                    "v": 0.0,
                    "w": 0.0,
                    "status": "arrived",
                    "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
                    "note": "dock",
                }

        # 7. Оценка модуля безопасности
        v_safe, w_safe, status, safety_note = self.safety.evaluate(
            v_cand=v_cand,
            w_cand=w_cand,
            v_odom=v_odom,
            w_odom=w_odom,
            pose=pose,
            odom_pose=odom_pose,
            tracks=active_tracks,
            ranges=ranges,
            rel_angles=rel_angles,
            zones=self.zones,
            is_fog=is_fog,
            is_arrived=self.arrived,
            is_lost=self.localizer.is_lost,
            blocked_wheels=self.localizer.blocked_wheels,
            perception_note=self.perception.note,
            remaining_dist=rem_dist,
            # Поперечная погрешность позы передается в примечание lost s_lat
            sigma_cross=self.localizer.sigma_cross,
        )

        # Объединение примечаний: активные причины безопасности приоритетнее заметок маршрута,
        # но устаревшие map_missing/map_extra не должны скрывать активный объезд.
        if route_note and safety_note in ("map_missing", "map_extra"):
            combined_note = route_note
        else:
            combined_note = safety_note or route_note or ""

        # Статус определяется по измеренной одометрии, пока платформа движется
        # При экстренном торможении (estop) сохраняется статус estop для включения тормоза 2.5 м/с2
        if status == "estop":
            final_status = "estop"
        elif abs(v_odom) > 0.04:
            final_status = "moving"
        else:
            final_status = status

        return {
            "v": float(v_safe),
            "w": float(w_safe),
            "status": final_status,
            "pose_est": [float(pose[0]), float(pose[1]), float(pose[2])],
            "note": combined_note,
        }
