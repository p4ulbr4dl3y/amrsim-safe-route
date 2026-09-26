"""Модуль сопоставления лидарных сканов со стенами и ориентирами карты.

Включает:
- прореживание лучей и фильтрацию одиночных снежинок по расстоянию между соседями;
- сопоставление методом Левенберга-Марквардта с адаптивным затуханием и функцией Хьюбера;
- проверку разброса нормалей и продольных ориентиров;
- штраф дисперсии за исчезновение ожидаемых стен в тумане;
- поиск по сетке для восстановления ориентации.

Соответствует требованиям Т3 и Т5 (только stdlib и numpy, относительные импорты).
"""

import math
from typing import List, Optional, Tuple

import numpy as np

try:
    from ..geom import filter_segs_aabb, point_to_segs_displacement, raycast, seg_dist, wrap_angle
except (ImportError, ValueError):
    from geom import filter_segs_aabb, point_to_segs_displacement, raycast, seg_dist, wrap_angle


class ScanMatchResult:
    """Результат сопоставления скана со стенами карты."""

    def __init__(
        self,
        success: bool,
        x: float,
        y: float,
        th: float,
        inliers: int,
        std: float,
        normals: Optional[np.ndarray],
        weights: Optional[np.ndarray],
        d_prev: np.ndarray,
        d_next: np.ndarray,
        finite_all: np.ndarray,
        near_segs: np.ndarray,
        r_sub: np.ndarray,
        rel_sub: np.ndarray,
    ):
        self.success = success
        self.x = x
        self.y = y
        self.th = th
        self.inliers = inliers
        self.std = std
        self.normals = normals
        self.weights = weights
        self.d_prev = d_prev
        self.d_next = d_next
        self.finite_all = finite_all
        self.near_segs = near_segs
        self.r_sub = r_sub
        self.rel_sub = rel_sub


def scan_has_angle(normals: Optional[np.ndarray]) -> bool:
    """Истина, когда инлайерные стены охватывают более ~30 град: виден реальный угол."""
    if normals is None or len(normals) < 2:
        return False
    ang = np.arctan2(normals[:, 1], normals[:, 0])
    r_len = math.hypot(float(np.cos(2.0 * ang).mean()), float(np.sin(2.0 * ang).mean()))
    return r_len < 0.866


def scan_holds_landmark(
    x: float,
    y: float,
    th: float,
    landmarks: Optional[np.ndarray],
    r_all: np.ndarray,
    rel_all: np.ndarray,
    d_prev: np.ndarray,
    d_next: np.ndarray,
    finite_all: np.ndarray,
    segs: np.ndarray,
) -> bool:
    """Истина, когда угол скана попадает на размеченный продольный ориентир."""
    if landmarks is None or len(landmarks) == 0 or segs is None or len(segs) == 0 or len(r_all) == 0:
        return False
    finite = finite_all & np.isfinite(r_all)
    jump = finite & ((d_prev > 1.5) | (d_next > 1.5))
    idx = np.flatnonzero(jump)
    if len(idx) == 0:
        return False

    ang = th + rel_all[idx]
    wx = x + r_all[idx] * np.cos(ang)
    wy = y + r_all[idx] * np.sin(ang)
    on_wall = np.atleast_1d(point_to_segs_displacement(wx, wy, segs).dists) < 0.35
    if not on_wall.any():
        return False
    wx = wx[on_wall]
    wy = wy[on_wall]
    for k in range(len(wx)):
        if float(np.min(np.hypot(landmarks[:, 0] - wx[k], landmarks[:, 1] - wy[k]))) < 2.0:
            return True
    return False


def apply_landmark_correction(
    x: float,
    y: float,
    th: float,
    var_along: float,
    var_cross: float,
    r_all: np.ndarray,
    rel_all: np.ndarray,
    d_prev: np.ndarray,
    d_next: np.ndarray,
    finite_all: np.ndarray,
    segs: np.ndarray,
    pole_centers: Optional[np.ndarray],
) -> Tuple[float, float, float, float, bool]:
    """Продольные ориентиры: коррекция слабой касательной оси по концам отрезков и столбам."""
    if segs is None or len(segs) == 0:
        return x, y, var_along, var_cross, False
    n = len(r_all)
    if n == 0:
        return x, y, var_along, var_cross, False

    finite = finite_all & np.isfinite(r_all)
    jump = finite & ((d_prev > 1.5) | (d_next > 1.5))
    idx = np.flatnonzero(jump)
    if len(idx) == 0:
        return x, y, var_along, var_cross, False

    ang = th + rel_all[idx]
    wx = x + r_all[idx] * np.cos(ang)
    wy = y + r_all[idx] * np.sin(ang)

    disp = point_to_segs_displacement(wx, wy, segs)
    dists = np.atleast_1d(disp.dists)
    seg_idx = np.atleast_1d(disp.seg_idx)
    on_wall = dists < 0.35
    if not on_wall.any():
        return x, y, var_along, var_cross, False

    poles = pole_centers
    have_poles = poles is not None and len(poles) > 0

    shifts: List[float] = []
    tangents: List[Tuple[float, float]] = []
    for k in np.flatnonzero(on_wall):
        si = int(seg_idx[k])
        if si < 0 or si >= len(segs):
            continue
        x1, y1, x2, y2 = (float(v) for v in segs[si][:4])
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len < 1e-6:
            continue
        tx, ty = (x2 - x1) / seg_len, (y2 - y1) / seg_len

        best_d = None
        best_xy = None
        for ex, ey in ((x1, y1), (x2, y2)):
            dd = math.hypot(ex - wx[k], ey - wy[k])
            if dd <= 0.6 and (best_d is None or dd < best_d):
                best_d, best_xy = dd, (ex, ey)
        if have_poles:
            pdd = np.hypot(poles[:, 0] - wx[k], poles[:, 1] - wy[k])
            pi = int(np.argmin(pdd))
            if float(pdd[pi]) <= 0.6 and (best_d is None or float(pdd[pi]) < best_d):
                best_d = float(pdd[pi])
                best_xy = (float(poles[pi, 0]), float(poles[pi, 1]))
        if best_xy is None:
            continue

        d_t = (best_xy[0] - wx[k]) * tx + (best_xy[1] - wy[k]) * ty
        if abs(d_t) < 0.3:
            continue
        shifts.append(max(-0.5, min(0.5, d_t)))
        tangents.append((tx, ty))

    if len(shifts) < 2:
        return x, y, var_along, var_cross, False

    shift = 0.5 * float(np.median(shifts))
    mtx = float(np.mean([t[0] for t in tangents]))
    mty = float(np.mean([t[1] for t in tangents]))
    mag = math.hypot(mtx, mty)
    if mag < 1e-6:
        return x, y, var_along, var_cross, False
    mtx /= mag
    mty /= mag
    new_x = x + shift * mtx
    new_y = y + shift * mty

    beta = math.atan2(mty, mtx)
    d_angle = wrap_angle(beta - th)
    cos_d2 = math.cos(d_angle) ** 2
    sin_d2 = math.sin(d_angle) ** 2
    var_t = var_along * cos_d2 + var_cross * sin_d2
    new_var_along = max(1e-6, var_along - 0.5 * var_t * cos_d2)
    new_var_cross = max(1e-6, var_cross - 0.5 * var_t * sin_d2)

    return new_x, new_y, new_var_along, new_var_cross, True


def penalise_missing_near_walls(
    x: float,
    y: float,
    th: float,
    var_along: float,
    var_cross: float,
    fog_var_added: float,
    r_sub: np.ndarray,
    rel_sub: np.ndarray,
    segs: np.ndarray,
) -> Tuple[float, float, float]:
    """В тумане ожидаемые ближние стены, дающие NaN, пачкой добавляют дисперсию."""
    if segs is None or len(segs) == 0:
        return var_along, var_cross, fog_var_added
    if fog_var_added >= 0.36:
        return var_along, var_cross, fog_var_added

    exp = raycast(x, y, th + rel_sub, segs)
    measured = np.isfinite(r_sub) & (r_sub > 0.1) & (r_sub < 5.5)
    missing = np.isfinite(exp) & (exp < 5.5) & ~measured
    if int(missing.sum()) < 12:
        return var_along, var_cross, fog_var_added

    ang = th + rel_sub[missing]
    mx = x + exp[missing] * np.cos(ang)
    my = y + exp[missing] * np.sin(ang)
    disp = point_to_segs_displacement(mx, my, segs)
    nx = float(np.mean(disp.normals[:, 0]))
    ny = float(np.mean(disp.normals[:, 1]))
    mag = math.hypot(nx, ny)
    inc = 0.02**2

    new_var_cross = var_cross
    new_var_along = var_along
    if mag < 1e-6:
        new_var_cross += inc
    else:
        alpha = math.atan2(ny / mag, nx / mag)
        d_angle = wrap_angle(alpha - th)
        new_var_cross += inc * math.sin(d_angle) ** 2
        new_var_along += inc * math.cos(d_angle) ** 2

    return new_var_along, new_var_cross, fog_var_added + inc


def recover_grid_search(
    x: float,
    y: float,
    th: float,
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    segs: np.ndarray,
    is_fog: bool = False,
) -> Optional[Tuple[float, float, float]]:
    """Иерархический поиск гипотез (Coarse-to-Fine CSM) при потере позы."""
    if segs is None or len(segs) == 0:
        return None

    r_all = np.asarray(ranges, dtype=float)
    rel_all = np.asarray(rel_angles, dtype=float)

    # Уровень 1 (Coarse): разреженный скан (шаг по лучам 4)
    step = 4
    r_coarse = r_all[::step]
    rel_coarse = rel_all[::step]

    max_range = 5.5 if is_fog else 19.0
    mask = np.isfinite(r_coarse) & (r_coarse > 0.1) & (r_coarse < max_range)
    if mask.sum() < 15:
        return None

    eval_r = r_coarse[mask]
    eval_rel = rel_coarse[mask]

    # Сетка Уровня 1: расширенный диапазон ±5.0 м с шагом 0.5 м, угол ±8° с шагом 0.08 рад
    dx_grid = np.arange(-5.0, 5.01, 0.5)
    dy_grid = np.arange(-5.0, 5.01, 0.5)
    dth_grid = np.arange(-np.radians(8.0), np.radians(8.01), 0.08)

    reach = 25.0
    local_segs = filter_segs_aabb(segs, x, y, reach + 5.5)
    if len(local_segs) == 0:
        return None

    candidates: List[Tuple[int, float, float, float]] = []
    for dth in dth_grid:
        cand_th = wrap_angle(th + dth)
        beam_angles = cand_th + eval_rel
        rx = eval_r * np.cos(beam_angles)
        ry = eval_r * np.sin(beam_angles)

        for dx in dx_grid:
            cx = x + dx
            pts_x = cx + rx
            for dy in dy_grid:
                cy = y + dy
                pts_y = cy + ry

                dists = seg_dist(pts_x, pts_y, local_segs)
                inliers = int((dists < 0.25).sum())
                candidates.append((inliers, cx, cy, cand_th))

    candidates.sort(key=lambda c: -c[0])
    if not candidates or candidates[0][0] < 15:
        return None

    # Кластеризация и отбор топ-3 лучших уникальных гипотез
    top_hypotheses: List[Tuple[int, float, float, float]] = []
    for c in candidates:
        score, cx, cy, cth = c
        is_close = False
        for _, ex, ey, eth in top_hypotheses:
            if (
                abs(cx - ex) <= 0.75
                and abs(cy - ey) <= 0.75
                and abs(wrap_angle(cth - eth)) <= math.radians(4.0)
            ):
                is_close = True
                break
        if not is_close:
            top_hypotheses.append(c)
            if len(top_hypotheses) >= 3:
                break

    # Уровень 2 (Fine): локальная оптимизация Levenberg-Marquardt вокруг отобранных кандидатов
    fine_results = []
    for _score, cx, cy, cth in top_hypotheses:
        res = match_scan_to_walls(cx, cy, cth, r_all, rel_all, segs, is_fog=is_fog)
        if res.success:
            fine_results.append((res.inliers, res.std, res.x, res.y, res.th))

    if fine_results:
        # Сортировка по числу инлайеров и минимальному СКО невязок
        fine_results.sort(key=lambda item: (-item[0], item[1]))
        _best_inliers, _best_std, fx, fy, fth = fine_results[0]
        return fx, fy, fth

    # Резервная эвристика по грубой сетке при недоборе инлайеров LM
    best_score, bx, by, bth = candidates[0]
    second_score = 0
    for score, cx, cy, cand_th in candidates[1:]:
        if (
            abs(cx - bx) > 0.75
            or abs(cy - by) > 0.75
            or abs(wrap_angle(cand_th - bth)) > math.radians(3.0)
        ):
            second_score = score
            break

    if best_score >= 35 and (
        best_score >= second_score * 1.15 or best_score - second_score >= 6
    ):
        return bx, by, bth

    return None


def match_scan_to_walls(
    x: float,
    y: float,
    th: float,
    ranges: np.ndarray,
    rel_angles: np.ndarray,
    segs: np.ndarray,
    is_fog: bool = False,
    segs_aabb: Optional[np.ndarray] = None,
) -> ScanMatchResult:
    """Сопоставление сканов со стенами карты методом Левенберга-Марквардта."""
    empty_res = ScanMatchResult(
        success=False,
        x=x,
        y=y,
        th=th,
        inliers=0,
        std=999.0,
        normals=None,
        weights=None,
        d_prev=np.empty(0),
        d_next=np.empty(0),
        finite_all=np.empty(0, dtype=bool),
        near_segs=np.empty((0, 4)),
        r_sub=np.empty(0),
        rel_sub=np.empty(0),
    )

    if segs is None or len(segs) == 0:
        return empty_res

    reach = 25.0
    near_segs_arr = filter_segs_aabb(segs, x, y, reach, aabb=segs_aabb)
    if len(near_segs_arr) == 0:
        return empty_res

    r_all = np.asarray(ranges, dtype=float)
    rel_all = np.asarray(rel_angles, dtype=float)

    step = 2
    r_sub = r_all[::step]
    rel_sub = rel_all[::step]

    max_valid_range = 5.5 if is_fog else 19.0
    valid_range_mask = np.isfinite(r_sub) & (r_sub > 0.1) & (r_sub < max_valid_range)

    sub_indices = np.arange(0, len(r_all), step)
    cos_rel_all = np.cos(rel_all)
    sin_rel_all = np.sin(rel_all)
    with np.errstate(invalid="ignore"):
        x_pts = r_all * cos_rel_all
        y_pts = r_all * sin_rel_all

    n_all = len(r_all)
    prev_idx = (np.arange(n_all) - 1) % n_all
    next_idx = (np.arange(n_all) + 1) % n_all

    finite_all = np.isfinite(r_all)
    d_prev = np.full(n_all, np.inf)
    d_next = np.full(n_all, np.inf)

    m_prev = finite_all & finite_all[prev_idx]
    m_next = finite_all & finite_all[next_idx]

    d_prev[m_prev] = np.hypot(
        x_pts[m_prev] - x_pts[prev_idx[m_prev]], y_pts[m_prev] - y_pts[prev_idx[m_prev]]
    )
    d_next[m_next] = np.hypot(
        x_pts[m_next] - x_pts[next_idx[m_next]], y_pts[m_next] - y_pts[next_idx[m_next]]
    )

    supported = (d_prev < 0.4) | (d_next < 0.4)
    supported_sub = supported[sub_indices]
    candidate_mask = valid_range_mask & supported_sub
    if candidate_mask.sum() < 20:
        return ScanMatchResult(
            success=False,
            x=x,
            y=y,
            th=th,
            inliers=0,
            std=999.0,
            normals=None,
            weights=None,
            d_prev=d_prev,
            d_next=d_next,
            finite_all=finite_all,
            near_segs=near_segs_arr,
            r_sub=r_sub,
            rel_sub=rel_sub,
        )

    cand_ranges = r_sub[candidate_mask]
    cand_rel = rel_sub[candidate_mask]

    cur_x = x
    cur_y = y
    cur_th = th

    inliers_count = 0
    final_std = 999.0
    last_normals = None
    last_weights = None

    huber_delta = 0.08
    lam = 1e-3
    lam_min = 1e-5
    lam_max = 1e4
    nu_down = 0.3
    nu_up = 3.0

    for _ in range(5):
        beam_world_angles = cur_th + cand_rel
        px = cur_x + cand_ranges * np.cos(beam_world_angles)
        py = cur_y + cand_ranges * np.sin(beam_world_angles)

        disp = point_to_segs_displacement(px, py, near_segs_arr)
        residuals = disp.dists
        normals = disp.normals

        dist_to_proj = np.hypot(disp.projs[:, 0] - cur_x, disp.projs[:, 1] - cur_y)
        not_short = cand_ranges >= dist_to_proj - 0.4

        inlier_mask = (residuals < 0.25) & not_short
        inliers_count = int(inlier_mask.sum())
        if inliers_count < 25:
            break

        res_inliers = residuals[inlier_mask]
        norm_inliers = normals[inlier_mask]
        px_inliers = px[inlier_mask]
        py_inliers = py[inlier_mask]
        cand_ranges_inliers = cand_ranges[inlier_mask]
        cand_rel_inliers = cand_rel[inlier_mask]

        abs_res = np.abs(res_inliers)
        weights = np.where(
            abs_res <= huber_delta, 1.0, huber_delta / np.maximum(abs_res, 1e-12)
        )
        cost = float(
            np.sum(
                np.where(
                    abs_res <= huber_delta,
                    0.5 * abs_res**2,
                    huber_delta * (abs_res - 0.5 * huber_delta),
                )
            )
        )

        rx = px_inliers - cur_x
        ry = py_inliers - cur_y

        J = np.column_stack(
            [
                norm_inliers[:, 0],
                norm_inliers[:, 1],
                -norm_inliers[:, 0] * ry + norm_inliers[:, 1] * rx,
            ]
        )

        W = weights[:, None]
        H = J.T @ (J * W)
        g = J.T @ (weights * res_inliers)

        # Диагональное демпфирование Левенберга-Марквардта:
        # np.maximum предохраняет от сингулярности гессиана вдоль неограниченных осей
        diag_H = np.maximum(np.diag(H), 1.0)
        D = np.diag(diag_H)

        step_accepted = False
        delta = np.zeros(3)

        for _attempt in range(4):
            H_damped = H + lam * D
            try:
                cand_delta = np.linalg.solve(H_damped, -g)
            except np.linalg.LinAlgError:
                lam = min(lam * nu_up, lam_max)
                continue

            cand_x = cur_x + float(cand_delta[0])
            cand_y = cur_y + float(cand_delta[1])
            cand_th = wrap_angle(cur_th + float(cand_delta[2]))

            c_beam_angles = cand_th + cand_rel_inliers
            c_px = cand_x + cand_ranges_inliers * np.cos(c_beam_angles)
            c_py = cand_y + cand_ranges_inliers * np.sin(c_beam_angles)
            c_disp = point_to_segs_displacement(c_px, c_py, near_segs_arr)
            c_abs = np.abs(c_disp.dists)
            cost_cand = float(
                np.sum(
                    np.where(
                        c_abs <= huber_delta,
                        0.5 * c_abs**2,
                        huber_delta * (c_abs - 0.5 * huber_delta),
                    )
                )
            )

            if cost_cand <= cost:
                cur_x = cand_x
                cur_y = cand_y
                cur_th = cand_th
                delta = cand_delta
                lam = max(lam * nu_down, lam_min)
                step_accepted = True
                break
            else:
                lam = min(lam * nu_up, lam_max)

        if not step_accepted:
            break

        if np.hypot(delta[0], delta[1]) < 0.0005 and abs(delta[2]) < 0.0005:
            break

    # Финальный расчет невязок и нормалей в сошедшейся позе
    beam_world_angles = cur_th + cand_rel
    px = cur_x + cand_ranges * np.cos(beam_world_angles)
    py = cur_y + cand_ranges * np.sin(beam_world_angles)

    disp = point_to_segs_displacement(px, py, near_segs_arr)
    residuals = disp.dists
    normals = disp.normals

    dist_to_proj = np.hypot(disp.projs[:, 0] - cur_x, disp.projs[:, 1] - cur_y)
    not_short = cand_ranges >= dist_to_proj - 0.4

    inlier_mask = (residuals < 0.25) & not_short
    inliers_count = int(inlier_mask.sum())

    if inliers_count >= 25:
        res_inliers = residuals[inlier_mask]
        last_normals = normals[inlier_mask]
        final_std = float(np.std(res_inliers))
        abs_res = np.abs(res_inliers)
        last_weights = np.where(
            abs_res <= huber_delta, 1.0, huber_delta / np.maximum(abs_res, 1e-12)
        )

    accepted = inliers_count >= 30 and final_std < 0.08
    return ScanMatchResult(
        success=accepted,
        x=cur_x,
        y=cur_y,
        th=cur_th,
        inliers=inliers_count,
        std=final_std,
        normals=last_normals,
        weights=last_weights,
        d_prev=d_prev,
        d_next=d_next,
        finite_all=finite_all,
        near_segs=near_segs_arr,
        r_sub=r_sub,
        rel_sub=rel_sub,
    )


class ScanMatcher:
    """Модуль сопоставления лидарных сканов со стенами карты."""

    match = staticmethod(match_scan_to_walls)
    has_angle = staticmethod(scan_has_angle)
    holds_landmark = staticmethod(scan_holds_landmark)
    apply_landmark_correction = staticmethod(apply_landmark_correction)
    penalise_missing_near_walls = staticmethod(penalise_missing_near_walls)
    recover_grid_search = staticmethod(recover_grid_search)
