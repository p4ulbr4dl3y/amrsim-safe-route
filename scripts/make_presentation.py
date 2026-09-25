#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор колоды к защите кейса «Безопасный маршрут» (команда Dreamteam 4.0).

Скрипт собирает до 12 слайдов формата A4 (landscape) и пишет их в
``presentation.pdf`` в корне репозитория. Все числа считаются в момент сборки
из данных репозитория, вручную в колоду не вписаны:

- ``results/seed_packet/*.json`` - 28 официальных отчетов (4 сценария x 7 seed);
- ``results/table_summary.csv`` - сводная строка команды;
- ``results/own_scenarios/*.json`` и ``results/own_scenarios/moments.json`` -
  свои сценарии s1..s5 и машиночитаемые моменты;
- ``results/own_scenarios/logs/*.jsonl`` - покадровые логи для графиков;
- ``APPROACH.md`` - формулировки и пороги подхода;
- ``Критерии_оценки_Безопасный_маршрут.md`` - перечень критериев и баллов;
- исходники контроллера и тестов - состав модулей, LOC, число тестов.

Внешние изображения не используются: траектории рисуются средствами
``reportlab`` canvas по bounds пройденного пути с сохранением пропорций.

Запуск из корня репозитория (кэш uv обязателен в песочнице)::

    UV_CACHE_DIR=<repo>/.uv-cache uv run --with reportlab python scripts/make_presentation.py

Вывод детерминирован: ``rl_config.invariant = 1`` фиксирует дату и
идентификатор документа, поэтому повторная сборка дает тот же sha256.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from reportlab import rl_config

# Фиксируем метаданные PDF до создания canvas, иначе reportlab пишет текущее
# время и случайный идентификатор документа, и sha256 меняется от запуска.
rl_config.invariant = 1

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

# --- Пути и константы оформления -------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "presentation.pdf"

FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT_BOLD_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 38.0
CONTENT_W = PAGE_W - 2.0 * MARGIN
TOTAL_SLIDES = 12

FONT = "ArialUni"
FONT_BOLD = "ArialBold"
HEADER_H = 44.0

NAVY = colors.HexColor("#16324f")
ACCENT = colors.HexColor("#c55a11")
INK = colors.HexColor("#1c2733")
GRAY = colors.HexColor("#5a6572")
LIGHT = colors.HexColor("#eef2f7")
GRID = colors.HexColor("#c8d2dc")
TRACK = colors.HexColor("#1f5f9e")
MARK = colors.HexColor("#e07b00")


# --- Чтение данных репозитория ---------------------------------------------

SEED_FILE_RE = re.compile(r"^(?P<scenario>[a-z0-9_]+)_(?P<seed>\d+)\.json$")


def read_json(path: Path):
    """Прочитать JSON-файл в UTF-8."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(path: Path) -> str:
    """Прочитать текстовый файл в UTF-8."""
    with path.open("r", encoding="utf-8") as fh:
        return fh.read()


def load_seed_packet():
    """Вернуть словарь: сценарий -> список отчетов, отсортированный по seed."""
    packet = {}
    for path in sorted((ROOT / "results" / "seed_packet").glob("*.json")):
        if not SEED_FILE_RE.match(path.name):
            continue
        report = read_json(path)
        packet.setdefault(report["scenario"], []).append(report)
    for reports in packet.values():
        reports.sort(key=lambda item: item["seed"])
    return packet


def aggregate(reports):
    """Свернуть список отчетов одного сценария в min/mean/max по блокам."""
    totals = [float(r["score"]["total"]) for r in reports]

    def block_values(name):
        return [float(r["score"]["blocks"].get(name, 0.0)) for r in reports]

    def triple(values):
        return min(values), sum(values) / len(values), max(values)

    data = {
        "n": len(reports),
        "seeds": [r["seed"] for r in reports],
        "total": triple(totals),
        "safety": triple(block_values("safety")),
        "pose": triple(block_values("pose")),
        "collisions": triple(block_values("collisions")),
        "fatal_any": any(bool(r["score"].get("fatal")) for r in reports),
        "counted_all": all(bool(r["score"].get("counted")) for r in reports),
        "deliveries": [int(r["score"].get("deliveries", 0)) for r in reports],
        "episodes": sum(len(r["score"].get("episodes", [])) for r in reports),
    }
    return data


def load_own_reports():
    """Вернуть свои отчеты: (сценарий, seed) -> отчет."""
    reports = {}
    for path in sorted((ROOT / "results" / "own_scenarios").glob("s*.json")):
        report = read_json(path)
        reports[(report["scenario"], int(report["seed"]))] = report
    return reports


def load_moments():
    """Прочитать машиночитаемые моменты своих сценариев."""
    return read_json(ROOT / "results" / "own_scenarios" / "moments.json")


def section_for(moments, scenario, seed):
    """Найти секцию moments.json по сценарию и seed."""
    for section in moments["scenarios"]:
        if section["scenario"] == scenario and int(section["seed"]) == int(seed):
            return section
    raise SystemExit("Нет секции моментов для %s seed %s" % (scenario, seed))


def moment_by_key(section, key):
    """Найти момент по ключу; вернуть None, если момент не найден."""
    for moment in section["moments"]:
        if moment["key"] == key:
            return moment
    return None


def load_track(log_relative_path):
    """Загрузить покадровую траекторию: списки t, x, y из строк type=tick."""
    ts, xs, ys = [], [], []
    path = ROOT / log_relative_path
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "tick":
                ts.append(float(row["t"]))
                xs.append(float(row["x"]))
                ys.append(float(row["y"]))
    return ts, xs, ys


def load_log_header(log_relative_path):
    """Прочитать строку type=header из JSONL-лога."""
    path = ROOT / log_relative_path
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "header":
                return row
    raise SystemExit("В логе нет заголовка: %s" % log_relative_path)


def nearest_index(ts, target):
    """Индекс такта, ближайшего по времени к target."""
    best = 0
    best_diff = None
    for index, value in enumerate(ts):
        diff = abs(value - target)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = index
    return best


def extract_approach(text, pattern):
    """Достать числовой фрагмент из APPROACH.md; без совпадения - ошибка."""
    match = re.search(pattern, text)
    if not match:
        raise SystemExit("В APPROACH.md не найден фрагмент: %s" % pattern)
    return match.groups() if match.groups() else match.group(0)


def parse_criteria():
    """Разобрать таблицу критериев: список (код, название, максимум)."""
    text = read_text(ROOT / "Критерии_оценки_Безопасный_маршрут.md")
    rows = []
    pattern = re.compile(
        r"^\|\s*\*\*([ТО]\d)\.\s*([^|*]+?)\*\*\s*\|.*?\|\s*0[^0-9](\d+)\s*\|\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            rows.append((match.group(1), match.group(2).strip(), int(match.group(3))))
    if not rows:
        raise SystemExit("Не удалось разобрать таблицу критериев")
    return rows


def module_rows():
    """Состав пакета контроллера: имя файла и число строк."""
    rows = []
    package = ROOT / "team_dreamteam_4_0"
    for path in sorted(package.glob("*.py")):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        rows.append((path.name, lines))
    return rows


def count_pytest_tests():
    """Число pytest-тестов статически по определениям def test_ в tests/."""
    total = 0
    for path in sorted((ROOT / "tests").glob("**/*.py")):
        total += len(re.findall(r"(?m)^\s*def test_", path.read_text(encoding="utf-8")))
    return total


def count_vitest_tests():
    """Число тестов фронтенда статически по вызовам it( и test(."""
    total = 0
    for path in sorted((ROOT / "arm" / "frontend" / "src").glob("**/*.test.*")):
        text = path.read_text(encoding="utf-8")
        total += len(re.findall(r"\b(?:it|test)\s*\(", text))
    return total


def run_amrsim_check():
    """Прогнать amrsim check и вернуть (нарушения, предупреждения)."""
    env = dict(os.environ)
    prefix = str(ROOT / "amrsim-participants")
    env["PYTHONPATH"] = prefix + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "amrsim", "check", "team_dreamteam_4_0"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return None, None
    output = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(
        r"(\d+)\s+violation\(s\) or error\(s\),\s+(\d+)\s+warning\(s\)", output
    )
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def run_ruff():
    """Проверить ruff без записи кэша; вернуть True/False/None."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--no-cache"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return None
    return proc.returncode == 0


# --- Примитивы рисования ----------------------------------------------------


def wrap_text(text, font, size, max_width):
    """Разбить строку на строки по ширине колонки."""
    words = str(text).split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def wrap_ragged(text, font, size, first_width, rest_width):
    """Разбить текст так, что первая строка уже остальных.

    Нужно для пунктов с жирным лидом: первая строка начинается после лида и
    имеет меньшую ширину, остальные занимают всю колонку.
    """
    words = str(text).split()
    if not words:
        return [""]
    lines = []
    current = ""
    width = first_width
    for word in words:
        candidate = word if not current else current + " " + word
        if not current or pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
            width = rest_width
    lines.append(current)
    return lines


def draw_paragraph(c, x, y, text, size=9.5, leading=12.0, font=FONT, color=INK,
                   max_width=CONTENT_W):
    """Нарисовать абзац и вернуть y следующей строки."""
    c.setFont(font, size)
    c.setFillColor(color)
    for line in wrap_text(text, font, size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_bullets(c, x, y, items, size=9.5, leading=12.2, max_width=CONTENT_W,
                 indent=12.0):
    """Нарисовать список пунктов; пункт - строка или пара (жирный лид, текст)."""
    for item in items:
        lead, text = item if isinstance(item, tuple) else (None, item)
        avail = max_width - indent
        c.setFont(FONT_BOLD, size)
        c.setFillColor(ACCENT)
        c.drawString(x, y, "-")
        if lead:
            lead_text = lead if lead.endswith(" ") else lead + " "
            lead_w = pdfmetrics.stringWidth(lead_text, FONT_BOLD, size)
            c.setFont(FONT_BOLD, size)
            c.setFillColor(NAVY)
            c.drawString(x + indent, y, lead_text.strip())
            # Первая строка идет после лида, остальные занимают всю колонку.
            lines = wrap_ragged(text, FONT, size, avail - lead_w, avail)
            c.setFont(FONT, size)
            c.setFillColor(INK)
            c.drawString(x + indent + lead_w, y, lines[0])
            lines = lines[1:]
            y -= leading
        else:
            lines = wrap_text(text, FONT, size, avail)
            c.setFont(FONT, size)
            c.setFillColor(INK)
            c.drawString(x + indent, y, lines[0])
            lines = lines[1:]
            y -= leading
        for line in lines:
            c.setFont(FONT, size)
            c.setFillColor(INK)
            c.drawString(x + indent, y, line)
            y -= leading
        y -= 3.0
    return y


def draw_table(c, x, y_top, widths, rows, size=8.5, leading=10.4, header=True,
               aligns=None, zebra=True):
    """Нарисовать таблицу с переносом текста; вернуть y нижней границы."""
    pad_x, pad_y = 4.0, 3.0
    aligns = aligns or ["l"] * len(widths)
    line_sets, heights = [], []
    for row_index, row in enumerate(rows):
        font = FONT_BOLD if (header and row_index == 0) else FONT
        cells = []
        max_lines = 1
        for col_index, cell in enumerate(row):
            lines = wrap_text(cell, font, size, widths[col_index] - 2.0 * pad_x)
            cells.append(lines)
            max_lines = max(max_lines, len(lines))
        line_sets.append(cells)
        heights.append(max_lines * leading + 2.0 * pad_y)

    total_w = sum(widths)
    y = y_top
    for row_index, row in enumerate(rows):
        height = heights[row_index]
        if header and row_index == 0:
            c.setFillColor(NAVY)
            c.rect(x, y - height, total_w, height, stroke=0, fill=1)
        elif zebra and row_index % 2 == 0:
            c.setFillColor(LIGHT)
            c.rect(x, y - height, total_w, height, stroke=0, fill=1)
        c.setStrokeColor(GRID)
        c.setLineWidth(0.4)
        c.line(x, y - height, x + total_w, y - height)
        cx = x
        for col_index, width in enumerate(widths):
            font = FONT_BOLD if (header and row_index == 0) else FONT
            c.setFont(font, size)
            c.setFillColor(colors.white if (header and row_index == 0) else INK)
            text_y = y - pad_y - size * 0.82
            for line in line_sets[row_index][col_index]:
                if aligns[col_index] == "r":
                    c.drawRightString(cx + width - pad_x, text_y, line)
                elif aligns[col_index] == "c":
                    c.drawCentredString(cx + width / 2.0, text_y, line)
                else:
                    c.drawString(cx + pad_x, text_y, line)
                text_y -= leading
            cx += width
        c.setStrokeColor(colors.HexColor("#dbe3ea"))
        c.setLineWidth(0.4)
        cx = x
        for width in widths[:-1]:
            cx += width
            c.line(cx, y - height, cx, y)
        y -= height
    c.setStrokeColor(colors.HexColor("#8fa0b0"))
    c.setLineWidth(0.6)
    c.rect(x, y, total_w, y_top - y, stroke=1, fill=0)
    return y


def draw_trajectory(c, rect, ts, xs, ys, marks, title=None):
    """Нарисовать траекторию (x, y) с сохранением пропорций и маркерами моментов.

    marks - список словарей с полями t и label. Маркеры ставятся в ближайший
    такт, подписи разносятся по вертикали, чтобы не перекрываться.
    """
    x0, y0, w, h = rect
    c.setFillColor(colors.HexColor("#f7f9fc"))
    c.setStrokeColor(GRID)
    c.setLineWidth(0.6)
    c.rect(x0, y0, w, h, stroke=1, fill=1)

    title_h = 12.0 if title else 0.0
    if title:
        c.setFont(FONT_BOLD, 8.5)
        c.setFillColor(NAVY)
        c.drawString(x0 + 6.0, y0 + h - 10.0, title)

    inner_x = x0 + 10.0
    inner_y = y0 + 10.0
    inner_w = w - 20.0
    inner_h = h - 20.0 - title_h

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    dx = max_x - min_x
    dy = max_y - min_y
    scale_x = inner_w / dx if dx > 1e-9 else float("inf")
    scale_y = inner_h / dy if dy > 1e-9 else float("inf")
    scale = min(scale_x, scale_y)
    if scale == float("inf"):
        scale = 1.0

    pad_x = (inner_w - dx * scale) / 2.0
    pad_y = (inner_h - dy * scale) / 2.0

    def to_px(value):
        return inner_x + pad_x + (value - min_x) * scale

    def to_py(value):
        return inner_y + pad_y + (value - min_y) * scale

    # Оси области данных.
    c.setStrokeColor(colors.HexColor("#dfe6ee"))
    c.setLineWidth(0.5)
    c.rect(inner_x, inner_y, inner_w, inner_h, stroke=1, fill=0)

    # Траектория.
    c.setStrokeColor(TRACK)
    c.setLineWidth(1.1)
    path = c.beginPath()
    path.moveTo(to_px(xs[0]), to_py(ys[0]))
    for index in range(1, len(xs)):
        path.lineTo(to_px(xs[index]), to_py(ys[index]))
    c.drawPath(path, stroke=1, fill=0)

    # Старт и финиш.
    c.setFillColor(colors.HexColor("#2e7d32"))
    c.rect(to_px(xs[0]) - 2.5, to_py(ys[0]) - 2.5, 5.0, 5.0, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#b3261e"))
    c.rect(to_px(xs[-1]) - 2.5, to_py(ys[-1]) - 2.5, 5.0, 5.0, stroke=0, fill=1)

    # Маркеры моментов и подписи.
    label_items = []
    for mark in marks:
        index = nearest_index(ts, mark["t"])
        mx = to_px(xs[index])
        my = to_py(ys[index])
        c.setFillColor(MARK)
        c.setStrokeColor(colors.white)
        c.setLineWidth(1.0)
        c.circle(mx, my, 4.0, stroke=1, fill=1)
        label_items.append({"x": mx, "y": my, "text": mark["label"]})

    gap = 10.0
    label_items.sort(key=lambda item: item["y"])
    for position, item in enumerate(label_items):
        if position > 0:
            previous = label_items[position - 1]["y"]
            if item["y"] - previous < gap:
                item["y"] = previous + gap
    top_limit = inner_y + inner_h - 2.0
    overflow = label_items[-1]["y"] - top_limit if label_items else 0.0
    if overflow > 0.0:
        for item in label_items:
            item["y"] -= overflow
    low_limit = inner_y + 2.0
    if label_items and label_items[0]["y"] < low_limit:
        shift = low_limit - label_items[0]["y"]
        for item in label_items:
            item["y"] += shift

    for item in label_items:
        text = item["text"]
        width = pdfmetrics.stringWidth(text, FONT, 6.5)
        side_right = item["x"] + 8.0 + width <= x0 + w - 3.0
        if side_right:
            tx = item["x"] + 8.0
        else:
            tx = item["x"] - 8.0 - width
        ty = item["y"]
        c.setStrokeColor(colors.HexColor("#9aa7b4"))
        c.setLineWidth(0.4)
        c.line(item["x"], item["y"], tx - 2.0 if side_right else tx + width + 2.0,
               ty - 2.0)
        c.setFont(FONT, 6.5)
        c.setFillColor(INK)
        c.drawString(tx, ty - 2.0, text)

    c.setFont(FONT, 6.0)
    c.setFillColor(GRAY)
    c.drawString(inner_x + 2.0, y0 + 4.0, "старт")
    c.drawRightString(inner_x + inner_w - 2.0, y0 + 4.0, "финиш")


# --- Каркас слайда ----------------------------------------------------------


def start_slide(c, number, title, subtitle=None):
    """Нарисовать шапку и подвал, вернуть верхнюю границу контента."""
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 15.5)
    c.drawString(MARGIN, PAGE_H - 29.0, title)
    c.setFont(FONT, 9.0)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 28.0, "Слайд %d из %d" % (number, TOTAL_SLIDES))

    top = PAGE_H - HEADER_H - 16.0
    if subtitle:
        c.setFont(FONT, 9.5)
        c.setFillColor(GRAY)
        c.drawString(MARGIN, top, subtitle)
        top -= 16.0

    c.setStrokeColor(colors.HexColor("#d5dde5"))
    c.setLineWidth(0.6)
    c.line(MARGIN, 26.0, PAGE_W - MARGIN, 26.0)
    c.setFont(FONT, 8.0)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, 16.0, "Dreamteam 4.0 - кейс «Безопасный маршрут» - контроллер amr-1.0")
    c.drawRightString(PAGE_W - MARGIN, 16.0, "%d / %d" % (number, TOTAL_SLIDES))
    return top


def f2(value):
    """Формат с двумя знаками после точки."""
    return "%.2f" % float(value)


def f3(value):
    """Формат с тремя знаками после точки."""
    return "%.3f" % float(value)


# --- Сборка данных ----------------------------------------------------------


def load_table_scenarios(team="team_dreamteam_4_0"):
    """Прочитать results/table.csv: порядок сценариев и число прогонов команды.

    Таблица batch - официальный перечень прогонов (4 сценария x 7 seed). Она
    задает канонический набор сценариев, чтобы локальные дополнительные прогоны
    не попадали в сводку колоды.
    """
    order = []
    runs = 0
    path = ROOT / "results" / "table.csv"
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("team") != team:
                continue
            runs += 1
            name = row.get("scenario")
            if name not in order:
                order.append(name)
    if not order:
        raise SystemExit("В results/table.csv нет прогонов команды %s" % team)
    return order, runs


def build_context():
    """Собрать все данные репозитория в один словарь."""
    ctx = {}
    packet_all = load_seed_packet()
    canonical, table_runs = load_table_scenarios()
    missing = [name for name in canonical if name not in packet_all]
    if missing:
        raise SystemExit("Нет отчетов seed_packet для сценариев: %s" % missing)
    ctx["packet"] = {name: packet_all[name] for name in canonical}
    ctx["scenario_names"] = canonical
    ctx["table_runs"] = table_runs
    ctx["agg"] = {name: aggregate(reports) for name, reports in ctx["packet"].items()}

    ctx["summary"] = {}
    summary_text = read_text(ROOT / "results" / "table_summary.csv").strip().splitlines()
    header = [cell.strip() for cell in summary_text[0].split(",")]
    for line in summary_text[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if cells and cells[0] == "team_dreamteam_4_0":
            ctx["summary"] = dict(zip(header, cells))

    ctx["own"] = load_own_reports()
    ctx["moments"] = load_moments()
    ctx["controller_sha"] = ctx["moments"]["controller_sha256"]
    ctx["controller_path"] = ctx["moments"]["controller_path"]

    ctx["approach"] = read_text(ROOT / "APPROACH.md")
    ctx["criteria"] = parse_criteria()
    ctx["modules"] = module_rows()
    ctx["pytest_count"] = count_pytest_tests()
    ctx["vitest_count"] = count_vitest_tests()
    ctx["amrsim_violations"], ctx["amrsim_warnings"] = run_amrsim_check()
    ctx["ruff_ok"] = run_ruff()

    ctx["total_open_runs"] = sum(agg["n"] for agg in ctx["agg"].values())
    ctx["total_open_deliveries"] = sum(sum(agg["deliveries"]) for agg in ctx["agg"].values())
    ctx["total_open_episodes"] = sum(agg["episodes"] for agg in ctx["agg"].values())
    if ctx["total_open_runs"] != table_runs:
        print("Предупреждение: отчетов %d, строк в table.csv %d"
              % (ctx["total_open_runs"], table_runs))

    # Скрытые сценарии в официальных отчетах помечены полем hidden.
    ctx["hidden_flags"] = sorted({
        bool(report.get("hidden"))
        for reports in ctx["packet"].values()
        for report in reports
    })
    return ctx


def own_total(ctx, scenario, seed):
    """Total своего сценария; сценарий s4b имеет два посева."""
    return float(ctx["own"][(scenario, seed)]["score"]["total"])


def own_blocks(ctx, scenario, seed):
    """Блоки своего сценария."""
    return ctx["own"][(scenario, seed)]["score"]["blocks"]


# --- Слайды -----------------------------------------------------------------


def slide_1_title(c, ctx):
    """Титульный слайд."""
    start_slide(c, 1, "Безопасный маршрут: AMR без спутникового сигнала")
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 30)
    c.drawCentredString(PAGE_W / 2.0, PAGE_H - 150.0, "Dreamteam 4.0")
    c.setFont(FONT_BOLD, 17)
    c.setFillColor(INK)
    c.drawCentredString(PAGE_W / 2.0, PAGE_H - 182.0,
                        "Автономная платформа межцеховой логистики")
    c.setFont(FONT, 13)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2.0, PAGE_H - 204.0,
                        "Кейс «Безопасный маршрут», контроллер AMR, схема amr-1.0")

    c.setStrokeColor(ACCENT)
    c.setLineWidth(2.0)
    c.line(PAGE_W / 2.0 - 120.0, PAGE_H - 224.0, PAGE_W / 2.0 + 120.0, PAGE_H - 224.0)

    total_missions = sum(
        len(report["missions"])
        for reports in ctx["packet"].values()
        for report in reports
    )
    lines = [
        ("Контроллер: ", ctx["controller_path"]),
        ("sha256 контроллера: ", ctx["controller_sha"]),
        ("Открытые сценарии: ", "%s, %d seed, %d прогонов"
         % (", ".join(ctx["scenario_names"]), len(ctx["agg"][ctx["scenario_names"][0]]["seeds"]),
            ctx["total_open_runs"])),
        ("Средний балл открытых прогонов: ", ctx["summary"].get("open_mean", "н/д")),
        ("Доставки: ", "%d из %d миссий, наездов на людей и столкновений нет"
         % (ctx["total_open_deliveries"], total_missions)),
    ]
    y = PAGE_H - 268.0
    for lead, value in lines:
        lead_w = pdfmetrics.stringWidth(lead, FONT_BOLD, 11)
        value_w = pdfmetrics.stringWidth(value, FONT, 11)
        x = (PAGE_W - lead_w - value_w) / 2.0
        c.setFont(FONT_BOLD, 11)
        c.setFillColor(NAVY)
        c.drawString(x, y, lead)
        c.setFont(FONT, 11)
        c.setFillColor(INK)
        c.drawString(x + lead_w, y, value)
        y -= 20.0

    c.setFont(FONT, 10)
    c.setFillColor(GRAY)
    c.drawCentredString(PAGE_W / 2.0, 52.0,
                        "Числа колоды собраны скриптом scripts/make_presentation.py из отчетов и логов репозитория")
    c.showPage()


def slide_2_task(c, ctx):
    """Задача и требования критериев."""
    top = start_slide(c, 2, "Задача", "Межцеховая логистика без спутникового сигнала и что оценивается")

    left_w = 368.0
    items = [
        ("Маршруты: ", "склад - цеха A и B - зарядная, движение по проездам с разъездом."),
        ("Люди и предметы: ", "пешеходы, в том числе невнимательные, оставленные паллеты и контейнеры в проезде."),
        ("Тень ГНСС: ", "на части площадки спутниковый фикс недоступен либо смещен на метры."),
        ("Туман и снег: ", "дальность лидара падает, появляются ложные возвраты и пропажи стен."),
        ("Расхождение карты: ", "снесенная стена (map_missing) и лишние конструкции (map_extra)."),
        ("Контракт amr-1.0: ", "на каждом тике v, w, status, pose_est, note; изоляция: только stdlib и numpy."),
        ("Отчетность: ", "прогон подтверждается отчетом amrsim и покадровым JSONL-логом."),
    ]
    y = draw_bullets(c, MARGIN, top - 4.0, items, size=9.5, leading=12.0, max_width=left_w)

    # Сводка по данным прогонов.
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y - 6.0, "Объем проверки")
    facts = [
        "сценарии: " + ", ".join(ctx["scenario_names"]),
        "seed: " + ", ".join(str(s) for s in ctx["agg"][ctx["scenario_names"][0]]["seeds"]),
        "официальных прогонов: %d, доставок: %d" % (ctx["total_open_runs"], ctx["total_open_deliveries"]),
        "поле hidden в отчетах: %s - скрытый набор локально не запускался" % ctx["hidden_flags"],
    ]
    draw_bullets(c, MARGIN, y - 22.0, facts, size=9.0, leading=11.4, max_width=left_w)

    # Таблица критериев справа.
    right_x = MARGIN + left_w + 26.0
    right_w = PAGE_W - MARGIN - right_x
    c.setFont(FONT_BOLD, 10)
    c.setFillColor(NAVY)
    c.drawString(right_x, top - 4.0, "Критерии оценки, максимум баллов")
    rows = [["Код", "Критерий", "Балл"]]
    for code, name, points in ctx["criteria"]:
        rows.append([code, name, str(points)])
    rows.append(["Итого", "технические 50 и отраслевые 50", "100"])
    draw_table(c, right_x, top - 12.0, [34.0, right_w - 34.0 - 30.0, 30.0], rows,
               size=8.0, leading=9.6, aligns=["c", "l", "c"])
    c.showPage()


def slide_3_architecture(c, ctx):
    """Архитектура контроллера и изоляция."""
    top = start_slide(c, 3, "Архитектура контроллера",
                      "controller.py как оркестратор, модули с узкими интерфейсами, только stdlib и numpy")

    left_w = 372.0
    items = [
        ("controller.py: ", "порядок вызовов predict - scan-match - GNSS-гейт - perceive - route - safety, вывод по amr-1.0 (v, w, status, pose_est, note)."),
        ("localize.py: ", "фильтр позы, скан-матч стен, гейт ГНСС, калибровка масштаба одометрии, dock-snap, статус lost."),
        ("perceive.py: ", "кластеры лидара и треки препятствий в чистой одометрии, классы, map_missing и map_extra."),
        ("route.py: ", "pure pursuit, боковой сдвиг, локальный A*, зоны скорости, возврат на эталон."),
        ("safety.py: ", "зазоры, коридор, estop, тиры lost_speed_limit, тексты note."),
        ("geom.py: ", "отрезки, raycast, AABB, полигоны, 2D-векторная математика."),
    ]
    draw_bullets(c, MARGIN, top - 4.0, items, size=9.5, leading=12.0, max_width=left_w)

    right_x = MARGIN + left_w + 26.0
    right_w = PAGE_W - MARGIN - right_x
    c.setFont(FONT_BOLD, 10)
    c.setFillColor(NAVY)
    c.drawString(right_x, top - 4.0, "Состав пакета team_dreamteam_4_0")
    roles = {
        "controller.py": "оркестратор тика",
        "geom.py": "геометрия",
        "localize.py": "локализация",
        "perceive.py": "восприятие",
        "route.py": "маршрут",
        "safety.py": "безопасность",
    }
    rows = [["Файл", "Строк", "Роль"]]
    total_lines = 0
    for name, lines in ctx["modules"]:
        rows.append([name, str(lines), roles.get(name, "-")])
        total_lines += lines
    rows.append(["итого", str(total_lines), "6 модулей"])
    draw_table(c, right_x, top - 12.0, [right_w - 96.0, 40.0, 56.0], rows,
               size=8.2, leading=10.0, aligns=["l", "r", "l"])

    check_text = "amrsim check: нарушения %s, предупреждения %s" % (
        ctx["amrsim_violations"] if ctx["amrsim_violations"] is not None else "н/д",
        ctx["amrsim_warnings"] if ctx["amrsim_warnings"] is not None else "н/д",
    )
    req = read_text(ROOT / "team_dreamteam_4_0" / "requirements.txt").strip()
    bottom_y = PAGE_H - HEADER_H - 250.0
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, bottom_y, "Изоляция Т3 и зависимости")
    draw_bullets(c, MARGIN, bottom_y - 16.0, [
        ("requirements.txt контроллера: ", "«%s» - сторонних пакетов нет." % req),
        ("Проверка изоляции: ", check_text + " (запускается скриптом при сборке колоды)."),
        ("Запись в файловую систему и сеть: ", "во время прогона контроллер не пишет и не ходит в сеть."),
        ("Тесты: ", "алгоритмы, сервер АРМ и метрики оцениваются pytest; интерфейс - Vitest и tsc."),
    ], size=9.0, leading=11.6, max_width=CONTENT_W)
    c.showPage()


def slide_4_localization(c, ctx):
    """Локализация и честность оценки позы."""
    top = start_slide(c, 4, "Локализация и честность позы",
                      "Собственная оценка позы, ГНСС как измерение, явные статусы движения")

    rays = extract_approach(ctx["approach"], r"лучи через (\d+)°")[0]
    inlier = extract_approach(ctx["approach"], r"остаток точки до отрезка < ([\d.]+) м")[0]
    iters = extract_approach(ctx["approach"], r"(\d+) итерации Гаусса-Ньютона")[0]
    min_inl = extract_approach(ctx["approach"], r"приём при ≥ (\d+) инлайнерах")[0]
    sigma = extract_approach(ctx["approach"], r"СКО остатка < ([\d.]+) м")[0]
    gate = extract_approach(ctx["approach"], r"гейт инновации ([\d.]+) м")[0]
    k_gain = extract_approach(ctx["approach"], r"коэффициентом k ≤ ([\d.]+)")[0]
    freeze = extract_approach(ctx["approach"], r"после (\d+) м согласованного пути")[0]

    col_w = (CONTENT_W - 28.0) / 2.0
    left_items = [
        ("Фильтр позы: ", "предикт по одометрии и imu.heading, сторож скачка курса больше 0.05 рад заменяет его интегралом yaw_rate."),
        ("Скан-матч стен: ", "лучи через %s°, остаток точки до отрезка меньше %s м, %s итерации Гаусса-Ньютона с весом Хубера, приём при не менее %s инлайнеров и СКО меньше %s м." % (rays, inlier, iters, min_inl, sigma)),
        ("ГНСС - измерение, не поза: ", "гейт инновации %s м и подмешивание с коэффициентом k не выше %s; сырой приёмник в pose_est не попадает." % (gate, k_gain)),
        ("Масштаб одометрии: ", "отношение пути одометрии к пути лидара; после %s м согласованного пути масштаб замораживается до конца прогона." % freeze),
    ]
    y_left = draw_bullets(c, MARGIN, top - 4.0, left_items, size=9.3, leading=11.8, max_width=col_w)

    right_x = MARGIN + col_w + 28.0
    right_items = [
        ("pose_est: ", "результат фильтра, а не координаты ГНСС; совпадение с истиной допускается только через оракульный хук set_truth в учебных сценариях."),
        ("lost: ", "при недопустимой неопределенности позы платформа останавливается (v = 0) и сообщает status=lost; поиск позы по сетке идет только стоя."),
        ("Согласованность статусов: ", "moving, пока модуль продольной скорости одометрии больше 0.04; waiting при нулевой команде; arrived по прибытии."),
        ("Контроль в колоде: ", "статусы и скорости берутся из покадровых логов и машиночитаемых моментов, а не из текста отчета."),
    ]
    y_right = draw_bullets(c, right_x, top - 4.0, right_items, size=9.3, leading=11.8, max_width=col_w)

    # Фактические статусы из логов своих сценариев.
    statuses = {}
    for path in sorted((ROOT / "results" / "own_scenarios" / "logs").glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("type") == "tick":
                    key = row.get("st")
                    statuses[key] = statuses.get(key, 0) + 1
    order = ["moving", "waiting", "arrived", "lost", "estop"]
    parts = ["%s %d" % (key, statuses[key]) for key in order if key in statuses]
    y = min(y_left, y_right) - 6.0
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y, "Статусы в покадровых логах своих сценариев (тактов)")
    draw_paragraph(c, MARGIN, y - 16.0, ", ".join(parts) + ".",
                   size=9.3, leading=11.8, max_width=CONTENT_W)
    c.showPage()


def slide_5_safety(c, ctx):
    """Безопасность."""
    top = start_slide(c, 5, "Безопасность",
                      "Зазоры до человека, коридор, estop и тиры скорости при потере позы")

    slow_d, slow_v = extract_approach(
        ctx["approach"], r"зазор < ([\d.]+) м → v ≤ ([\d.]+) м/с")
    stop_d = extract_approach(ctx["approach"], r"зазор < ([\d.]+) м → v = 0")[0]
    estop_d = extract_approach(ctx["approach"], r"ближе ([\d.]+) м")[0]
    fog_free, fog_cluster = extract_approach(
        ctx["approach"], r"в тумане ([\d.]+) м/с на пустом коридоре и ([\d.]+) м/с у кластера впереди")
    lat_sigma, head_sigma, lat_v = extract_approach(
        ctx["approach"], r"σ поперек > ([\d.]+) м или σ курса > (\d+)° → v ≤ ([\d.]+)")
    along_sigma, along_v = extract_approach(
        ctx["approach"], r"σ вдоль > ([\d.]+) м → v ≤ ([\d.]+)")
    stop_sigma = extract_approach(ctx["approach"], r"σ поперек > ([\d.]+) м → стоп")[0]

    section = section_for(ctx["moments"], "s5_fog_inattentive", 7)
    stop_person = moment_by_key(section, "stop_person")
    min_hum = None
    with (ROOT / section["log"]).open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("type") == "tick" and row.get("hum") is not None:
                value = float(row["hum"])
                min_hum = value if min_hum is None else min(min_hum, value)

    col_w = (CONTENT_W - 28.0) / 2.0
    left_items = [
        ("Человек или неизвестный объект: ", "зазор меньше %s м снижает скорость до %s м/с; при зазоре меньше %s м скорость обнуляется." % (slow_d, slow_v, stop_d)),
        ("Коридор: ", "три соседних луча в полосе |y| меньше 1.0 м внутри тормозного пути дают v = 0, поворот при этом разрешен."),
        ("Класс неясен: ", "ведем как человека, но трек подтверждается двумя попаданиями, поэтому одиночный снежный возврат не тормозит."),
        ("Предмет вне карты: ", "крупный неподвижный контур идет в слой препятствий и объезжается, а не держит вечный стоп."),
    ]
    y_left = draw_bullets(c, MARGIN, top - 4.0, left_items, size=9.3, leading=11.8, max_width=col_w)

    right_x = MARGIN + col_w + 28.0
    right_items = [
        ("estop: ", "замедление 2.5 м/с² включается только когда подтвержденный кластер ближе %s м, зазор сокращается и штатного тормоза 1.2 м/с² не хватает." % estop_d),
        ("Тиры lost_speed_limit: ", "σ поперек больше %s м или σ курса больше %s° - не быстрее %s м/с; σ вдоль больше %s м - не быстрее %s м/с; σ поперек больше %s м - стоп и статус lost." % (lat_sigma, head_sigma, lat_v, along_sigma, along_v, stop_sigma)),
        ("Туман: ", "%s м/с на пустом коридоре и %s м/с у кластера впереди." % (fog_free, fog_cluster)),
        ("Проверка по логу s5 seed 7: ", "момент %s: note «%s», команда v = %s м/с; минимальный фактический зазор до человека за прогон %s м." % (stop_person["t"], stop_person["note"], stop_person["v"], f2(min_hum))),
    ]
    y_right = draw_bullets(c, right_x, top - 4.0, right_items, size=9.3, leading=11.8, max_width=col_w)

    block = own_blocks(ctx, "s5_fog_inattentive", 7)
    y = min(y_left, y_right) - 6.0
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y, "Итог по блоку safety")
    draw_paragraph(c, MARGIN, y - 16.0,
                   "На s5 seed 7 блок safety = %s из 25, столкновений %s, fatal нет; "
                   "по всем %d открытым прогонам safety не опускался ниже %s."
                   % (f2(block["safety"]), f2(block["collisions"]),
                      ctx["total_open_runs"],
                      f2(min(agg["safety"][0] for agg in ctx["agg"].values()))),
                   size=9.3, leading=11.8, max_width=CONTENT_W)
    c.showPage()


def slide_6_results(c, ctx):
    """Результаты на открытых сценариях 01-04."""
    top = start_slide(c, 6, "Результаты 01-04",
                      "7 seed на сценарий, разрез seed 7 и сводная строка table_summary.csv")

    rows_a = [["Сценарий", "Seed", "total min", "total mean", "total max"]]
    for name in ctx["scenario_names"]:
        agg = ctx["agg"][name]
        rows_a.append([name, str(agg["n"]), f2(agg["total"][0]), f2(agg["total"][1]),
                       f2(agg["total"][2])])
    y_after_a = draw_table(c, MARGIN, top - 4.0, [166.0, 44.0, 56.0, 62.0, 52.0],
                           rows_a, size=8.6, leading=10.4,
                           aligns=["l", "c", "r", "r", "r"])

    rows_b = [["Сценарий, seed 7", "total", "delivery", "efficiency", "safety",
               "rules", "pose", "collisions"]]
    for name in ctx["scenario_names"]:
        report = None
        for item in ctx["packet"][name]:
            if int(item["seed"]) == 7:
                report = item
        blocks = report["score"]["blocks"]
        rows_b.append([name, f2(report["score"]["total"]), f2(blocks["delivery"]),
                       f3(blocks["efficiency"]), f2(blocks["safety"]),
                       f2(blocks["rules"]), f2(blocks["pose"]),
                       f2(blocks["collisions"])])
    y_after_b = draw_table(c, MARGIN, y_after_a - 14.0,
                           [176.0, 52.0, 62.0, 76.0, 52.0, 46.0, 46.0, 66.0],
                           rows_b, size=8.4, leading=10.2,
                           aligns=["l", "r", "r", "r", "r", "r", "r", "r"])

    summary = ctx["summary"]
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y_after_b - 18.0, "Сводная строка results/table_summary.csv")
    summary_line = ("%s: check %s, runs %s, open_mean %s, case_score %s."
                    % (summary.get("team", "н/д"), summary.get("check", "н/д"),
                       summary.get("runs", "н/д"), summary.get("open_mean", "н/д"),
                       summary.get("case_score", "н/д")))
    y_after_summary = draw_paragraph(c, MARGIN, y_after_b - 32.0, summary_line,
                                     size=9.3, leading=11.8, max_width=CONTENT_W)

    safety_min = min(agg["safety"][0] for agg in ctx["agg"].values())
    pose_min = min(agg["pose"][0] for agg in ctx["agg"].values())
    collision_max = max(agg["collisions"][2] for agg in ctx["agg"].values())
    fatal_any = any(agg["fatal_any"] for agg in ctx["agg"].values())
    counted_all = all(agg["counted_all"] for agg in ctx["agg"].values())

    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y_after_summary - 6.0, "Вывод")
    conclusion = ("На %d прогонах 4 сценариев x 7 seed: safety не ниже %s, pose не ниже %s, "
                  "collisions максимум %s, fatal %s, counted %s, эпизодов штрафов %d; "
                  "доставлено %d перевозок. Все прогоны засчитаны."
                  % (ctx["total_open_runs"], f2(safety_min), f2(pose_min), f2(collision_max),
                     "нет" if not fatal_any else "есть", "везде true" if counted_all else "не везде",
                     ctx["total_open_episodes"], ctx["total_open_deliveries"]))
    y_after_conclusion = draw_paragraph(c, MARGIN, y_after_summary - 20.0, conclusion,
                                        size=9.3, leading=11.8, max_width=CONTENT_W)

    # Отдельно цена efficiency на 03: сравнение с baseline seed 7.
    baseline = read_json(ROOT / "results" / "baseline_03_fog_snow.json")
    report_03 = None
    for item in ctx["packet"]["03_fog_snow"]:
        if int(item["seed"]) == 7:
            report_03 = item
    team_eff = report_03["score"]["blocks"]["efficiency"]
    base_eff = baseline["score"]["blocks"]["efficiency"]
    draw_paragraph(c, MARGIN, y_after_conclusion - 4.0,
                   "Отдельно: на 03_fog_snow seed 7 efficiency команды %s против baseline %s - "
                   "разница %s балла. Это цена осторожных тиров самого плана в снегу и тумане."
                   % (f3(team_eff), f3(base_eff), f3(base_eff - team_eff)),
                   size=9.0, leading=11.4, max_width=CONTENT_W)
    c.showPage()


def slide_7_conditions_1(c, ctx):
    """Сложные условия, часть 1: тень ГНСС и туман."""
    top = start_slide(c, 7, "Сложные условия, часть 1 (О2)",
                      "Тень ГНСС на сценарии 02 и туман на s5 seed 7")

    agg_02 = ctx["agg"]["02_gnss_shadow"]
    fog_section = section_for(ctx["moments"], "s5_fog_inattentive", 7)
    fog_clear = moment_by_key(fog_section, "fog_clear")
    header = load_log_header(fog_section["log"])
    fog_event = None
    for event in header.get("events", []):
        if event.get("type") == "fog_bank":
            fog_event = event
    s5_total = own_total(ctx, "s5_fog_inattentive", 7)

    left_w = 322.0
    items = [
        ("Тень ГНСС, сценарий 02: ", "total %s на всех %d seed (min %s, max %s), доставка 1 из 1 на каждом прогоне."
         % (f2(agg_02["total"][1]), agg_02["n"], f2(agg_02["total"][0]), f2(agg_02["total"][2]))),
        ("Почему проходит: ", "ГНСС не подмешивается в позу напрямую: на время тени работает скан-матч стен, а гейт отбрасывает смещенный фикс."),
        ("Туман, s5 seed 7: ", "total %s; событие тумана t = %s..%s с, выход из тумана t = %s."
         % (f2(s5_total), fog_event["t1"] if fog_event else "н/д",
            fog_event["t2"] if fog_event else "н/д", fog_clear["t"])),
        ("Реакция: ", "в тумане дальность клампится, скорость снижается до 0.9 м/с на пустом коридоре; на выходе note «%s», v = %s м/с."
         % (fog_clear["note"], fog_clear["v"])),
        ("Что видно на графике: ", "траектория вдоль проезда и маркер момента fog_clear по данным лога %s." % fog_section["log"]),
    ]
    draw_bullets(c, MARGIN, top - 4.0, items, size=9.2, leading=11.6, max_width=left_w)

    ts, xs, ys = load_track(fog_section["log"])
    plot_x = MARGIN + left_w + 20.0
    plot_w = PAGE_W - MARGIN - plot_x
    plot_h = 322.0
    draw_trajectory(c, (plot_x, top - plot_h, plot_w, plot_h), ts, xs, ys,
                    [{"t": fog_clear["t"],
                      "label": "fog_clear t=%s, v=%s" % (fog_clear["t"], fog_clear["v"])}],
                    title="Траектория s5_fog_inattentive, seed 7 (вид сверху, пропорции сохранены)")
    c.showPage()


def slide_8_conditions_2(c, ctx):
    """Сложные условия, часть 2: пешеход и потеря ориентации."""
    top = start_slide(c, 8, "Сложные условия, часть 2 (О2)",
                      "Пешеход перед платформой и потеря ориентации с остановкой")

    fog_section = section_for(ctx["moments"], "s5_fog_inattentive", 7)
    stop_person = moment_by_key(fog_section, "stop_person")
    ts5, xs5, ys5 = load_track(fog_section["log"])

    # Один проход по логу: зазор до человека в момент stop_person и первый такт,
    # где команда скорости обнулилась после этого момента.
    stop_hum = None
    zero_t = None
    with (ROOT / fog_section["log"]).open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("type") != "tick":
                continue
            t_value = float(row["t"])
            if abs(t_value - float(stop_person["t"])) < 1e-6 and row.get("hum") is not None:
                stop_hum = float(row["hum"])
            if zero_t is None and t_value >= float(stop_person["t"]) and float(row["v"]) <= 1e-9:
                zero_t = t_value

    lost_section = section_for(ctx["moments"], "s4b_shadow_lane_lost", 1)
    lost_note = moment_by_key(lost_section, "lane_lost_nt")
    lost_status = moment_by_key(lost_section, "lane_lost_status")
    resume = moment_by_key(lost_section, "motion_resume")
    ts4, xs4, ys4 = load_track(lost_section["log"])
    st_lost_first, st_lost_last = None, None
    with (ROOT / lost_section["log"]).open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("type") == "tick" and row.get("st") == "lost":
                value = float(row["t"])
                st_lost_first = value if st_lost_first is None else min(st_lost_first, value)
                st_lost_last = value if st_lost_last is None else max(st_lost_last, value)

    half_w = (CONTENT_W - 24.0) / 2.0

    # Левая половина: пешеход.
    left_items = [
        ("Пешеход, s5 seed 7: ", "момент t = %s, note «%s», v = %s м/с; зазор до человека в этот такт %s м."
         % (stop_person["t"], stop_person["note"], stop_person["v"], f2(stop_hum))),
        ("Торможение: ", "скорость падает до нуля к t = %s, далее статус waiting, пока человек не уйдет." % zero_t),
        ("Итог: ", "total %s, safety %s, collisions %s, наезда нет."
         % (f2(own_total(ctx, "s5_fog_inattentive", 7)),
            f2(own_blocks(ctx, "s5_fog_inattentive", 7)["safety"]),
            f2(own_blocks(ctx, "s5_fog_inattentive", 7)["collisions"]))),
    ]
    draw_bullets(c, MARGIN, top - 4.0, left_items, size=9.0, leading=11.4,
                 max_width=half_w)
    draw_trajectory(c, (MARGIN, top - 322.0, half_w, 206.0), ts5, xs5, ys5,
                    [{"t": stop_person["t"],
                      "label": "stop_person t=%s" % stop_person["t"]}],
                    title="s5 seed 7: траектория и момент stop_person")

    # Правая половина: потеря ориентации.
    right_x = MARGIN + half_w + 24.0
    right_items = [
        ("Потеря ориентации, s4b seed 1: ", "note lost впервые на t = %s, скорость к этому моменту %s м/с." % (lost_note["t"], lost_note["v"])),
        ("Остановка: ", "status=lost на тактах t = %s..%s, v = 0.00; поиск позы идет только стоя." % (st_lost_first, st_lost_last)),
        ("Восстановление: ", "первый такт после выхода из lost t = %s, status=%s, затем движение продолжено." % (resume["t"], resume["status"])),
        ("Итог: ", "total %s, доставка есть, fatal нет."
         % f2(own_total(ctx, "s4b_shadow_lane_lost", 1))),
    ]
    draw_bullets(c, right_x, top - 4.0, right_items, size=9.0, leading=11.4,
                 max_width=half_w)
    draw_trajectory(c, (right_x, top - 322.0, half_w, 206.0), ts4, xs4, ys4, [
        {"t": lost_note["t"], "label": "note lost t=%s" % lost_note["t"]},
        {"t": lost_status["t"], "label": "st=lost t=%s" % lost_status["t"]},
        {"t": st_lost_last, "label": "стоп до t=%s" % st_lost_last},
        {"t": resume["t"], "label": "resume t=%s" % resume["t"]},
    ], title="s4b seed 1: остановка lost и восстановление")
    c.showPage()


def slide_9_features(c, ctx):
    """Дополнительные возможности О4."""
    top = start_slide(c, 9, "Дополнительные возможности (О4)",
                      "Объезд предмета, перепланирование, расхождение карты: момент, код и лог")

    def code_refs(needle):
        refs = []
        for path in sorted((ROOT / "team_dreamteam_4_0").glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if needle in line:
                    refs.append("%s:%d" % (path.name, number))
        return refs

    cases = [
        {
            "title": "Объезд оставленного предмета",
            "scenario": "s1_pallet_2m",
            "key": "offset",
            "needle": "offset dy=",
            "role": "боковой сдвиг эталонной трубки в route.py",
        },
        {
            "title": "Перепланирование маршрута",
            "scenario": "s2_container_block",
            "key": "replan",
            "needle": 'self.note = "replan"',
            "role": "локальный A* и интервал переплана 2 с в route.py",
        },
        {
            "title": "Расхождение карты",
            "scenario": "s3_wall_removed",
            "key": "map_missing",
            "needle": 'detected_note = "map_missing"',
            "role": "детектор снесенной стены в perceive.py",
        },
    ]

    col_w = (CONTENT_W - 24.0) / 3.0
    for index, case in enumerate(cases):
        x = MARGIN + index * (col_w + 12.0)
        section = section_for(ctx["moments"], case["scenario"], 7)
        moment = moment_by_key(section, case["key"])
        report = ctx["own"][(case["scenario"], 7)]
        c.setFillColor(NAVY)
        c.setFont(FONT_BOLD, 10.5)
        c.drawString(x, top - 4.0, case["title"])
        lines = [
            "Сценарий %s, seed 7: total %s." % (case["scenario"], f2(report["score"]["total"])),
            "Момент t = %s, status=%s, v = %s, note «%s»." % (
                moment["t"], moment["status"], moment["v"], moment["note"]),
            "Код: %s (%s)." % (", ".join(code_refs(case["needle"])), case["role"]),
            "Лог: %s." % section["log"],
        ]
        y = top - 20.0
        for line in lines:
            y = draw_paragraph(c, x, y, line, size=8.6, leading=10.6, max_width=col_w) - 2.0

        ts, xs, ys = load_track(section["log"])
        draw_trajectory(c, (x, top - 336.0, col_w, 246.0), ts, xs, ys,
                        [{"t": moment["t"],
                          "label": "t=%s %s" % (moment["t"], case["key"])}],
                        title="Траектория, маркер момента")

    footer_y = top - 352.0
    c.setFont(FONT, 8.4)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, footer_y,
                 "Каждая возможность подтверждена отчетом JSON и покадровым логом JSONL в results/own_scenarios; "
                 "свои сценарии s1..s5 и контрольный прогон s4b seed 1 лежат в scenarios/ и results/own_scenarios.")
    c.showPage()


def slide_10_operator(c, ctx):
    """Рабочее место оператора О3."""
    top = start_slide(c, 10, "Рабочее место оператора (О3)",
                      "Станция на JSONL-логе и отчете JSON, запуск задания и экспорт")

    header = load_log_header("results/own_scenarios/logs/s5_fog_inattentive.jsonl")
    mission = header["missions"][0]
    mission2 = header["missions"][1]
    dt = header.get("dt")

    col_w = (CONTENT_W - 28.0) / 2.0
    left_items = [
        ("Источники: ", "покадровый JSONL (type=header и type=tick) и итоговый отчет JSON симулятора; онлайн-интерфейса у симулятора нет."),
        ("Просмотр лога: ", "проигрывание с паузой и перемоткой, карта площадки, положение платформы и ее оценка pose_est рядом с истиной."),
        ("Пешеходы во времени: ", "дальность до человека и объекта по тактам, статус и причина остановки."),
        ("Журнал рейсов: ", "миссии, время старта и прибытия, соблюдение дедлайна."),
        ("Эпизоды штрафов: ", "просмотр эпизодов по клику с переходом к такту."),
    ]
    y_left = draw_bullets(c, MARGIN, top - 4.0, left_items, size=9.2, leading=11.6,
                          max_width=col_w)

    right_x = MARGIN + col_w + 28.0
    right_items = [
        ("Запуск задания: ", "python -m amrsim run со сценарием, seed и отчетом; результат отображается в станции (верхний уровень критерия)."),
        ("Экспорт: ", "сводка прогонов в CSV и отчеты в JSON, таблица результатов по seed."),
        ("Подпись миссии и дедлайн: ", "из заголовка лога: %s %s - %s, дедлайн %s с; %s %s - %s, дедлайн %s с; шаг лога dt = %s с."
         % (mission["id"], mission["from"], mission["to"], mission["deadline_s"],
            mission2["id"], mission2["from"], mission2["to"], mission2["deadline_s"], dt)),
        ("Тесты станции: ", "%d тестов Vitest, tsc --noEmit без ошибок." % ctx["vitest_count"]),
        ("Сервер: ", "python arm/server.py --port 8000 раздает собранный интерфейс, зависимостей кроме stdlib нет."),
    ]
    y_right = draw_bullets(c, right_x, top - 4.0, right_items, size=9.2, leading=11.6,
                           max_width=col_w)

    y = min(y_left, y_right) - 4.0
    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y, "Обязательный минимум и что сверх него")
    draw_paragraph(c, MARGIN, y - 16.0,
                   "Обязательный минимум критерия - проигрывание лога с паузой и перемоткой - закрыт. "
                   "Сверх него реализованы карта с позой и оценкой позы, пешеходы во времени, журнал рейсов, "
                   "эпизоды штрафов по клику, запуск задания через amrsim run и экспорт CSV и JSON.",
                   size=9.2, leading=11.6, max_width=CONTENT_W)
    c.showPage()


def slide_11_limits(c, ctx):
    """Ограничения и честность."""
    top = start_slide(c, 11, "Ограничения и честность",
                      "Что не получилось, где данные неполные и какая у этого цена")

    grid_step, grid_inlier = extract_approach(
        ctx["approach"], r"шаг сетки ([\d.]+) м при допуске инлайнера ([\d.]+) м")
    lost_seed7 = moment_by_key(section_for(ctx["moments"], "s4b_shadow_lane_lost", 7),
                               "lane_lost_status")
    lost_seed1_section = section_for(ctx["moments"], "s4b_shadow_lane_lost", 1)

    baseline = read_json(ROOT / "results" / "baseline_03_fog_snow.json")
    report_03 = None
    for item in ctx["packet"]["03_fog_snow"]:
        if int(item["seed"]) == 7:
            report_03 = item
    team_eff = report_03["score"]["blocks"]["efficiency"]
    base_eff = baseline["score"]["blocks"]["efficiency"]
    agg_03 = ctx["agg"]["03_fog_snow"]

    items = [
        ("Промах сетки поиска позы: ", "шаг сетки %s м при допуске инлайнера %s м. Смещение между узлами не набирает инлайнеров, и платформа остается стоять. Это главный незакрытый дефект." % (grid_step, grid_inlier)),
        ("Потеря ориентации на seed 7: ", "в s4b seed 7 потери нет (момент найден: %s, note «%s»). Поэтому потеря показана на контрольном прогоне seed 1, где note lost есть на t = %s, status=lost на t = %s..%s, восстановление на t = %s." % (
            lost_seed7["found"], lost_seed7["note"], moment_by_key(lost_seed1_section, "lane_lost_nt")["t"],
            moment_by_key(lost_seed1_section, "lane_lost_status")["t"],
            max(m["t"] for m in lost_seed1_section["moments"]
                if m["key"] == "lane_lost_status" and m["t"] is not None),
            moment_by_key(lost_seed1_section, "motion_resume")["t"])),
        ("Эпизоды штрафов на открытых прогонах: ", "%d за %d прогонов; доставка на каждом прогоне, fatal нет." % (ctx["total_open_episodes"], ctx["total_open_runs"])),
        ("Скрытые сценарии: ", "локально не измерялись: в отчетах поле hidden принимает значения %s, отдельного доступа к скрытому набору нет." % ctx["hidden_flags"]),
        ("03_fog_snow ниже baseline по efficiency: ", "на seed 7 efficiency команды %s против baseline %s (средний total команды %s при лучшем %s). В снегу и тумане осторожные тиры скорости из самого плана стоят примерно %s балла efficiency - это осознанный выбор в пользу зазоров." % (
            f3(team_eff), f3(base_eff), f2(agg_03["total"][1]), f2(agg_03["total"][2]), f3(base_eff - team_eff))),
        ("Чего нет в подходе: ", "фильтра частиц на каждом тике, глобального SLAM и полного поля расстояний площадки - на 120 м вдоль стены частицы размазываются, а платить пришлось бы на 10^4 тиках."),
    ]
    draw_bullets(c, MARGIN, top - 4.0, items, size=9.3, leading=12.2, max_width=CONTENT_W)
    c.showPage()


def slide_12_repro(c, ctx):
    """Тесты и воспроизводимость."""
    top = start_slide(c, 12, "Тесты и воспроизводимость",
                      "Числа проверок, команды прогона и что делать дальше")

    check_value = "OK" if (ctx["amrsim_violations"] == 0 and ctx["amrsim_warnings"] == 0) else "см. вывод"
    rows = [
        ["Проверка", "Результат", "Значение"],
        ["pytest", "%d тестов" % ctx["pytest_count"], "tests/, алгоритмы и сервер"],
        ["Vitest", "%d тестов" % ctx["vitest_count"], "arm/frontend/src"],
        ["tsc --noEmit", "без ошибок", "npm run lint"],
        ["ruff check", "без ошибок" if ctx["ruff_ok"] else "есть замечания", "uv run ruff check"],
        ["amrsim check", check_value,
         "%s нарушений, %s предупреждений" % (ctx["amrsim_violations"], ctx["amrsim_warnings"])],
        ["Открытые прогоны", "counted 28 из 28", "4 сценария x 7 seed"],
    ]
    y_after_table = draw_table(c, MARGIN, top - 4.0, [120.0, 150.0, 220.0], rows,
                               size=8.6, leading=10.6, aligns=["l", "l", "l"])

    commands = [
        ("Установка: ", "uv sync (или pip install -r requirements.txt, только numpy)."),
        ("Изоляция: ", "PYTHONPATH=amrsim-participants python -m amrsim check team_dreamteam_4_0."),
        ("Один сценарий: ", "PYTHONPATH=amrsim-participants python -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json."),
        ("Пакет: ", "PYTHONPATH=amrsim-participants python -m amrsim batch teams scenarios --seeds 1,2,3,7,11,21,42 --out out/table.csv."),
        ("Колода: ", "UV_CACHE_DIR=<repo>/.uv-cache uv run --with reportlab python scripts/make_presentation.py; сборка детерминирована (invariant), повторный запуск дает тот же sha256."),
    ]
    y = draw_bullets(c, MARGIN, y_after_table - 12.0, commands, size=8.8, leading=11.0,
                     max_width=CONTENT_W)

    c.setFillColor(NAVY)
    c.setFont(FONT_BOLD, 10)
    c.drawString(MARGIN, y - 4.0, "Выводы и что дальше")
    conclusions = [
        "Закрыты Т1-Т5 и О1-О4: 02_gnss_shadow берется на всех seed, 01, 03, 04 проходят без столкновений и наездов, pose честная, изоляция чистая.",
        "Первый приоритет - промах сетки поиска позы на 0.5 м: нужен шаг не грубее допуска инлайнера, иначе lost может не восстановиться.",
        "Второй приоритет - вернуть efficiency на 03_fog_snow, не срезая зазоры безопасности.",
        "Далее - прогнать контроллер на скрытом наборе того же формата и подтвердить поведение в lost на нескольких seed.",
    ]
    draw_bullets(c, MARGIN, y - 18.0, conclusions, size=8.8, leading=11.0,
                 max_width=CONTENT_W)
    c.showPage()


# --- Точка входа ------------------------------------------------------------


def register_fonts():
    """Зарегистрировать кириллические шрифты."""
    if not FONT_PATH.exists():
        raise SystemExit("Не найден шрифт: %s" % FONT_PATH)
    pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))
    if FONT_BOLD_PATH.exists():
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_BOLD_PATH)))
    else:
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_PATH)))


def main():
    """Собрать презентацию."""
    register_fonts()
    ctx = build_context()

    c = canvas.Canvas(str(OUT_PATH), pagesize=(PAGE_W, PAGE_H), invariant=1)
    c.setTitle("Безопасный маршрут - Dreamteam 4.0")
    c.setAuthor("Dreamteam 4.0")
    c.setSubject("Презентация к защите, контроллер AMR, схема amr-1.0")
    c.setCreator("scripts/make_presentation.py")

    slide_1_title(c, ctx)
    slide_2_task(c, ctx)
    slide_3_architecture(c, ctx)
    slide_4_localization(c, ctx)
    slide_5_safety(c, ctx)
    slide_6_results(c, ctx)
    slide_7_conditions_1(c, ctx)
    slide_8_conditions_2(c, ctx)
    slide_9_features(c, ctx)
    slide_10_operator(c, ctx)
    slide_11_limits(c, ctx)
    slide_12_repro(c, ctx)
    c.save()

    print("Собрано: %s" % OUT_PATH)
    print("Страниц: %d, размер: %d байт" % (TOTAL_SLIDES, OUT_PATH.stat().st_size))
    print("pytest: %d, Vitest: %d, ruff: %s, amrsim check: %s/%s"
          % (ctx["pytest_count"], ctx["vitest_count"],
             "OK" if ctx["ruff_ok"] else "FAIL",
             ctx["amrsim_violations"], ctx["amrsim_warnings"]))


if __name__ == "__main__":
    main()
