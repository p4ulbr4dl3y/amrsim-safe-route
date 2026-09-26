#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверки утверждений колоды до того, как они попадут на слайд.

Озвучиваемые слайды не содержат sha отчетов. Чужой sha открытого пакета
допустим только на резервном слайде, который этот модуль не рисует.
"""

from __future__ import annotations

import re


def format_score(value):
    """Балл без хвостовых нулей, иначе два знака."""
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return "%d" % int(round(number))
    return "%.2f" % number


def format_score_span(values):
    """Один балл или диапазон min-max."""
    if not values:
        raise ValueError("пустой набор баллов")
    lo = min(float(value) for value in values)
    hi = max(float(value) for value in values)
    if abs(lo - hi) < 1e-9:
        return format_score(lo)
    return "%s-%s" % (format_score(lo), format_score(hi))


def assert_spoken_text(text, banned_shas):
    """Вернуть текст слайда 1-8 либо остановить сборку, если в нем есть sha."""
    body = str(text)
    for sha in banned_shas:
        token = str(sha or "").strip()
        if len(token) >= 8 and token in body:
            raise SystemExit("Озвучиваемый слайд содержит sha отчета: %s" % token)
    return body


def open_packet_title(run_count, shas, current_sha, mean_text):
    """Заголовок резервного слайда открытого пакета."""
    unique = sorted({sha for sha in shas if sha})
    if unique == [current_sha]:
        return "%d прогонов этого кода. Среднее %s." % (run_count, mean_text)
    shown = ", ".join(unique) if unique else "н/д"
    return "%d прогонов, sha %s. Среднее %s." % (run_count, shown, mean_text)


def open_packet_subtitle(shas, current_sha, hidden_any):
    """Подзаголовок: чей это код и есть ли скрытые прогоны."""
    unique = {sha for sha in shas if sha}
    if unique != {current_sha}:
        head = "Это не результат текущего controller.py."
    else:
        head = "Открытые сценарии 01-04."
    if hidden_any:
        tail = "В пакете есть скрытые прогоны."
    else:
        tail = "Скрытых прогонов в пакете нет."
    return "%s %s" % (head, tail)


def numpy_only(lines):
    """True, если каждая непустая строка requirements - пакет numpy."""
    names = []
    for line in lines:
        name = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return bool(names) and all(name == "numpy" for name in names)


def parse_distance(note):
    """Достать d=... из note такта."""
    match = re.search(r"d=([0-9]+(?:\.[0-9]+)?)", note or "")
    if not match:
        raise ValueError("в note нет дистанции d=")
    return float(match.group(1))


def note_of(tick):
    """Текст заметки такта: поле note либо nt, как пишет amrsim."""
    if tick.get("note"):
        return str(tick["note"])
    nt = tick.get("nt")
    return "" if nt is None else str(nt)


def nearest_tick(ticks, target_t, tol=0.051):
    """Такт лога, ближайший к моменту; дальше допуска - ошибка."""
    if not ticks:
        raise ValueError("пустой лог")
    best = min(ticks, key=lambda row: abs(float(row["t"]) - float(target_t)))
    if abs(float(best["t"]) - float(target_t)) > tol:
        raise ValueError("нет такта около t=%s" % target_t)
    return best


def assert_moment_on_tick(moment, tick, fragment):
    """Сверить статус, скорость и фрагмент note момента с тактом лога."""
    status = moment.get("status")
    if status and tick.get("st") != status:
        raise ValueError(
            "статус момента %s, в логе %s" % (status, tick.get("st"))
        )
    if moment.get("v") is not None and abs(float(tick.get("v", 0.0)) - float(moment["v"])) > 0.02:
        raise ValueError(
            "скорость момента %s, в логе %s" % (moment.get("v"), tick.get("v"))
        )
    if fragment and fragment not in note_of(tick):
        raise ValueError("в такте нет фрагмента %s, note=%s" % (fragment, note_of(tick)))


def lost_run(ticks):
    """Сплошной участок st=lost и первый такт после него с v>0."""
    indexes = [index for index, tick in enumerate(ticks) if tick.get("st") == "lost"]
    if not indexes:
        raise ValueError("в логе нет тактов lost")
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise ValueError("такты lost идут не сплошным участком")
    resume_t = None
    for tick in ticks[indexes[-1] + 1 :]:
        if float(tick.get("v") or 0.0) > 0.0:
            resume_t = float(tick["t"])
            break
    return {
        "count": len(indexes),
        "t0": float(ticks[indexes[0]]["t"]),
        "t1": float(ticks[indexes[-1]]["t"]),
        "resume_t": resume_t,
    }


def efficiency_is_only_gap(blocks, maxima):
    """True, если от максимума отстает только блок efficiency."""
    short = []
    for name, cap in maxima.items():
        value = float(blocks.get(name, 0.0))
        if float(cap) - value > 0.001:
            short.append(name)
    return short == ["efficiency"]


def assert_pure_pursuit_combat(step_body):
    """Боевой step() следования вызывает pure pursuit и не вызывает запасные законы."""
    if "self.pure_pursuit(" not in step_body:
        raise ValueError("step() не вызывает pure_pursuit")
    if "self.stanley(" in step_body:
        raise ValueError("step() вызывает stanley")
    if "quintic" in step_body:
        raise ValueError("step() вызывает quintic")


def assert_cbf_not_wired(controller_source):
    """Боевой контроллер не ссылается на неподключенный барьер скорости."""
    if "cbf_velocity_limit" in controller_source:
        raise ValueError("controller.py содержит cbf_velocity_limit")
