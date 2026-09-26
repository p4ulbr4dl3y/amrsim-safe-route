#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Колода к защите кейса «Безопасный маршрут» (Dreamteam 4.0).

12 страниц 16:9 в ``presentation.pdf``. Слайды 1-8 озвучиваются: один тезис,
без sha. Слайды 9-12 резерв для файла. Числа читаются из отчетов и логов
в момент сборки. Сборка останавливается, если озвучиваемый текст содержит
sha отчета или момент не совпадает с тактом лога.

Запуск из корня репозитория::

    uv run --with reportlab python scripts/make_presentation.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from reportlab import rl_config

rl_config.invariant = 1

from reportlab.lib import colors  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

try:
    from presentation_claims import (
        assert_cbf_not_wired,
        assert_moment_on_tick,
        assert_pure_pursuit_combat,
        assert_spoken_text,
        efficiency_is_only_gap,
        format_score,
        format_score_span,
        lost_run,
        nearest_tick,
        numpy_only,
        open_packet_subtitle,
        open_packet_title,
        parse_distance,
    )
except ImportError:  # запуск как scripts.make_presentation из pytest не нужен
    from scripts.presentation_claims import (  # type: ignore
        assert_cbf_not_wired,
        assert_moment_on_tick,
        assert_pure_pursuit_combat,
        assert_spoken_text,
        efficiency_is_only_gap,
        format_score,
        format_score_span,
        lost_run,
        nearest_tick,
        numpy_only,
        open_packet_subtitle,
        open_packet_title,
        parse_distance,
    )


ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "presentation.pdf"

FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT_BOLD_PATH = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

# 13.333 x 7.5 дюйма, ровно 16:9.
PAGE_W = 960.0
PAGE_H = 540.0
MARGIN = 56.0
CONTENT_W = PAGE_W - 2.0 * MARGIN
TOTAL_SLIDES = 12

FONT = "ArialUni"
FONT_BOLD = "ArialBold"

NAVY = colors.HexColor("#16324f")
ACCENT = colors.HexColor("#c55a11")
INK = colors.HexColor("#1c2733")
GRAY = colors.HexColor("#5c6670")
PAPER = colors.HexColor("#f6f4f0")
CARD = colors.HexColor("#fffcf8")
LINE = colors.HexColor("#e4ddd4")

# Свои прогоны, снятые на текущий файл контроллера. s4b seed 7 в диапазон
# не входит: на нем потеря ориентации не возникает.
SPOKEN_OWN = (
    ("s1_pallet_2m", 7),
    ("s2_container_block", 7),
    ("s3_wall_removed", 7),
    ("s4_shadow_start_charger", 7),
    ("s4b_shadow_lane_lost", 1),
    ("s5_fog_inattentive", 7),
)

SEED_FILE_RE = re.compile(r"^(?P<scenario>[a-z0-9_]+)_(?P<seed>\d+)\.json$")


def read_json(path):
    """Прочитать JSON в UTF-8."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    """Прочитать текст в UTF-8."""
    with path.open("r", encoding="utf-8") as handle:
        return handle.read()


def must_find(text, pattern, label):
    """Группа 1 из документа. Нет совпадения - сборка падает."""
    match = re.search(pattern, text)
    if not match:
        raise SystemExit("В исходном тексте нет фрагмента (%s): %s" % (label, pattern))
    return match.group(1)


def controller_sha256():
    """Первые 16 hex sha256 файла controller.py, как их пишет amrsim."""
    path = ROOT / "team_dreamteam_4_0" / "controller.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_seed_packet():
    """Сценарий -> отчеты seed_packet, по возрастанию seed."""
    packet = {}
    for path in sorted((ROOT / "results" / "seed_packet").glob("*.json")):
        if not SEED_FILE_RE.match(path.name):
            continue
        report = read_json(path)
        packet.setdefault(report["scenario"], []).append(report)
    for reports in packet.values():
        reports.sort(key=lambda item: item["seed"])
    return packet


def load_own_reports():
    """Свои отчеты: (сценарий, seed) -> отчет."""
    reports = {}
    for path in sorted((ROOT / "results" / "own_scenarios").glob("s*.json")):
        report = read_json(path)
        reports[(report["scenario"], int(report["seed"]))] = report
    return reports


def section_for(moments, scenario, seed):
    """Секция moments.json."""
    for section in moments["scenarios"]:
        if section["scenario"] == scenario and int(section["seed"]) == int(seed):
            return section
    raise SystemExit("Нет секции моментов для %s seed %s" % (scenario, seed))


def moment_by_key(section, key):
    """Момент по ключу. Найденный момент обязателен."""
    for moment in section["moments"]:
        if moment["key"] == key:
            if not moment.get("found", True):
                raise SystemExit("Момент %s не найден в %s" % (key, section["scenario"]))
            return moment
    raise SystemExit("Нет ключа %s в %s seed %s" % (key, section["scenario"], section["seed"]))


def load_ticks(log_relative):
    """Строки type=tick из JSONL."""
    ticks = []
    path = ROOT / log_relative
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("type") == "tick":
                ticks.append(row)
    if not ticks:
        raise SystemExit("В логе нет тактов: %s" % log_relative)
    return ticks


def method_body(source, method_name):
    """Тело метода класса с отступом 4 пробела, до следующего метода."""
    lines = source.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^    def %s\(" % re.escape(method_name), line):
            start = index
            break
    if start is None:
        raise SystemExit("Не найден метод %s" % method_name)
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("    def ") or line.startswith("class "):
            break
        body.append(line)
    return "\n".join(body)


def count_pytest_tests():
    """Число pytest по определениям def test_ в tests/."""
    total = 0
    for path in sorted((ROOT / "tests").glob("**/*.py")):
        total += len(re.findall(r"(?m)^\s*def test_", path.read_text(encoding="utf-8")))
    return total


def root_requirement_lines():
    """Непустые строки корневого requirements.txt без комментариев."""
    lines = []
    for raw in read_text(ROOT / "requirements.txt").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def run_amrsim_check():
    """Прогнать amrsim check. Нет разбора вывода - сборка падает."""
    env = dict(os.environ)
    prefix = str(ROOT / "amrsim-participants")
    env["PYTHONPATH"] = prefix + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "amrsim", "check", "team_dreamteam_4_0"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(
        r"(\d+)\s+violation\(s\) or error\(s\),\s+(\d+)\s+warning\(s\)", output
    )
    if not match:
        raise SystemExit("amrsim check не разобран:\n%s" % output[-500:])
    return int(match.group(1)), int(match.group(2))


def report_sha(report):
    """sha контроллера из отчета."""
    return (report.get("controller") or {}).get("sha256") or ""


def require_current(report, current, label):
    """Отчет озвучиваемого слайда обязан быть снят текущим controller.py."""
    sha = report_sha(report)
    if sha != current:
        raise SystemExit(
            "Отчет %s снят sha %s, текущий controller.py %s"
            % (label, sha or "н/д", current)
        )


def load_summary_row():
    """Строка team_dreamteam_4_0 из table_summary.csv."""
    path = ROOT / "results" / "table_summary.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("team") == "team_dreamteam_4_0":
            return row
    raise SystemExit("В table_summary.csv нет строки команды")


def canonical_scenarios():
    """Порядок открытых сценариев из table.csv."""
    order = []
    path = ROOT / "results" / "table.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("team") != "team_dreamteam_4_0":
                continue
            name = row.get("scenario")
            if name and name not in order:
                order.append(name)
    if not order:
        raise SystemExit("В results/table.csv нет прогонов команды")
    return order


def say(ctx, text):
    """Зафиксировать строку озвучиваемого слайда и запретить sha."""
    clean = assert_spoken_text(text, ctx["banned_shas"])
    ctx["spoken"].append(clean)
    return clean


def build_context():
    """Собрать факты колоды. Озвучиваемая половина уже проверена по sha и логам."""
    current = controller_sha256()
    moments = read_json(ROOT / "results" / "own_scenarios" / "moments.json")
    if moments.get("controller_sha256") != current:
        raise SystemExit(
            "moments.json sha %s, controller.py %s"
            % (moments.get("controller_sha256"), current)
        )

    own = load_own_reports()
    spoken_reports = []
    for scenario, seed in SPOKEN_OWN:
        report = own.get((scenario, seed))
        if report is None:
            raise SystemExit("Нет своего отчета %s seed %s" % (scenario, seed))
        require_current(report, current, "%s seed %s" % (scenario, seed))
        if not report["score"].get("counted"):
            raise SystemExit("Прогон %s seed %s не засчитан" % (scenario, seed))
        if report["score"].get("fatal"):
            raise SystemExit("Прогон %s seed %s fatal" % (scenario, seed))
        if float(report["score"]["blocks"].get("collisions", 0.0)) != 0.0:
            raise SystemExit("Прогон %s seed %s имеет столкновения" % (scenario, seed))
        missions = report.get("missions") or []
        if not missions or not all(item.get("delivered") for item in missions):
            raise SystemExit("Прогон %s seed %s сдал не все миссии" % (scenario, seed))
        spoken_reports.append(report)

    approach = read_text(ROOT / "APPROACH.md")
    alternatives = read_text(ROOT / "results" / "ALTERNATIVES.md")
    task = read_text(ROOT / "Постановка_задачи_Безопасный_маршрут.md")
    criteria = read_text(ROOT / "Критерии_оценки_Безопасный_маршрут.md")
    facts = {
        "gnss_median": must_find(approach, r"медиана ошибки ГНСС (0\.46) м", "медиана ГНСС"),
        "dock": must_find(approach, r"допуском дока (0\.2) м", "док"),
        "wall_m": must_find(alternatives, r"длиной (120) м", "стена"),
        "steps": must_find(approach, r"на (10\^4) шагов", "шаги"),
        "fog": must_find(approach, r"в тумане (0\.9) м/с на пустом коридоре", "туман"),
        "window": must_find(approach, r"в окне (±5 м)", "окно поиска"),
        "grid": must_find(approach, r"шаг сетки (0\.5) м", "шаг сетки"),
        "limit_min": must_find(
            criteria, r"(10 минут) реального времени", "лимит времени"
        ),
        "baseline": must_find(criteria, r"не проходит (02)", "база 02"),
        "shadow_m": must_find(task, r"последние (143) м", "тень"),
        "yard": must_find(task, r"(250 x 200) м", "площадка"),
        "fog_see": must_find(task, r"в тумане только на (6) м", "видимость"),
    }

    controller_source = read_text(ROOT / "team_dreamteam_4_0" / "controller.py")
    follower_source = read_text(ROOT / "team_dreamteam_4_0" / "route" / "follower.py")
    try:
        assert_cbf_not_wired(controller_source)
        assert_pure_pursuit_combat(method_body(follower_source, "step"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    def checked_moment(scenario, seed, key, fragment):
        section = section_for(moments, scenario, seed)
        moment = moment_by_key(section, key)
        ticks = load_ticks(section["log"])
        tick = nearest_tick(ticks, moment["t"])
        try:
            assert_moment_on_tick(moment, tick, fragment)
        except ValueError as exc:
            raise SystemExit("%s %s: %s" % (scenario, key, exc)) from exc
        return moment, ticks, section

    s4_arrival, _, _ = checked_moment(
        "s4_shadow_start_charger", 7, "arrival_charger", "dock"
    )
    s5_fog, _, _ = checked_moment("s5_fog_inattentive", 7, "fog_clear", "fog_clear")
    yard_person, _, yard_section = checked_moment(
        "04_busy_yard", 7, "stop_person", "stop_person"
    )
    s3_wall, _, _ = checked_moment("s3_wall_removed", 7, "map_missing", "map_missing")
    s1_offset, _, s1_section = checked_moment("s1_pallet_2m", 7, "offset", "offset")
    s2_replan, _, s2_section = checked_moment(
        "s2_container_block", 7, "replan", "replan"
    )
    s4b_lost, s4b_ticks, _ = checked_moment(
        "s4b_shadow_lane_lost", 1, "lane_lost_status", "lost"
    )
    try:
        lost = lost_run(s4b_ticks)
    except ValueError as exc:
        raise SystemExit("s4b: %s" % exc) from exc
    if abs(lost["t0"] - float(s4b_lost["t"])) > 0.051:
        raise SystemExit("Первый lost в логе не совпал с моментом")
    if lost["resume_t"] is None:
        raise SystemExit("После lost скорость так и не стала положительной")

    person_distance = parse_distance(yard_person["note"])
    yard_report = read_json(ROOT / yard_section["report"])
    s5_report = own[("s5_fog_inattentive", 7)]
    if not efficiency_is_only_gap(s5_report["score"]["blocks"], s5_report["score"]["max"]):
        raise SystemExit("s5 потерял не только эффективность, слайд 7 так говорить нельзя")

    packet_all = load_seed_packet()
    names = canonical_scenarios()
    missing = [name for name in names if name not in packet_all]
    if missing:
        raise SystemExit("Нет отчетов seed_packet: %s" % ", ".join(missing))
    packet = {name: packet_all[name] for name in names}
    flat = [report for name in names for report in packet[name]]
    packet_shas = [report_sha(report) for report in flat]
    totals = [float(report["score"]["total"]) for report in flat]
    mean = sum(totals) / len(totals)
    summary = load_summary_row()
    summary_mean = float(summary["open_mean"]) if summary.get("open_mean") else None
    if summary_mean is not None and abs(summary_mean - mean) > 0.02:
        raise SystemExit(
            "table_summary open_mean %s, среднее отчетов %s" % (summary_mean, mean)
        )
    hidden_any = any(bool(report.get("hidden")) for report in flat)

    violations, warnings = run_amrsim_check()
    if violations != 0 or warnings != 0:
        raise SystemExit("amrsim check: %d нарушений, %d предупреждений" % (violations, warnings))

    requirements = root_requirement_lines()
    banned = {current}
    banned.update(sha for sha in packet_shas if sha)

    ctx = {
        "current_sha": current,
        "banned_shas": banned,
        "spoken": [],
        "facts": facts,
        "own_totals": [float(report["score"]["total"]) for report in spoken_reports],
        "own_n": len(spoken_reports),
        "s4_arrival": s4_arrival,
        "s5_fog": s5_fog,
        "s5_total": float(s5_report["score"]["total"]),
        "yard_person": yard_person,
        "yard_distance": person_distance,
        "yard_total": float(yard_report["score"]["total"]),
        "yard_log": yard_section["log"],
        "s3_wall": s3_wall,
        "s3_total": float(own[("s3_wall_removed", 7)]["score"]["total"]),
        "s4_total": float(own[("s4_shadow_start_charger", 7)]["score"]["total"]),
        "s1_offset": s1_offset,
        "s1_total": float(own[("s1_pallet_2m", 7)]["score"]["total"]),
        "s1_log": s1_section["log"],
        "s2_replan": s2_replan,
        "s2_total": float(own[("s2_container_block", 7)]["score"]["total"]),
        "s2_log": s2_section["log"],
        "lost": lost,
        "packet_names": names,
        "packet": packet,
        "packet_shas": packet_shas,
        "packet_mean": mean,
        "packet_n": len(flat),
        "hidden_any": hidden_any,
        "same_sha": set(packet_shas) == {current},
        "pytest_count": count_pytest_tests(),
        "requirements": requirements,
        "numpy_only": numpy_only(requirements),
        "check_violations": violations,
        "check_warnings": warnings,
    }
    return ctx


def wrap_lines(text, font, size, max_width):
    """Перенос по словам."""
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


def draw_text(c, x, y, text, font, size, leading, color, max_width, align="left"):
    """Абзац. x для center - центр строки. Вернуть y под блоком."""
    lines = wrap_lines(text, font, size, max_width)
    c.setFont(font, size)
    c.setFillColor(color)
    for line in lines:
        if align == "center":
            c.drawCentredString(x, y, line)
        else:
            c.drawString(x, y, line)
        y -= leading
    return y


def begin_slide(c, number):
    """Поле, левая плашка акцента, номер страницы."""
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(ACCENT)
    c.rect(0, 0, 8, PAGE_H, stroke=0, fill=1)
    c.setFillColor(GRAY)
    c.setFont(FONT, 11)
    c.drawRightString(PAGE_W - 36, 22, "%d / %d" % (number, TOTAL_SLIDES))


def end_slide(c):
    """Закрыть страницу."""
    c.showPage()


def slide_claim(c, ctx, number, title, supports):
    """Озвучиваемый кадр: заголовок-вывод и короткие строки под ним."""
    begin_slide(c, number)
    title_clean = say(ctx, title)
    support_clean = [say(ctx, line) for line in supports]
    title_lines = wrap_lines(title_clean, FONT_BOLD, 34, CONTENT_W)
    support_line_count = sum(
        len(wrap_lines(line, FONT, 20, CONTENT_W)) for line in support_clean
    )
    block_h = len(title_lines) * 42 + 18 + support_line_count * 28
    y = (PAGE_H + block_h) / 2.0 - 34
    y = draw_text(
        c, MARGIN, y, title_clean, FONT_BOLD, 34, 42, NAVY, CONTENT_W
    )
    y -= 8
    for line in support_clean:
        y = draw_text(c, MARGIN, y, line, FONT, 20, 28, INK, CONTENT_W)
        y -= 6
    end_slide(c)


def slide_1(c, ctx):
    """Титул."""
    begin_slide(c, 1)
    line_a = say(ctx, "Док без спутника.")
    line_b = say(ctx, "Людей не касаемся.")
    team = say(ctx, "Dreamteam 4.0")
    case = say(ctx, "Кейс «Безопасный маршрут»")
    c.setFillColor(ACCENT)
    c.rect(MARGIN, 318, 72, 4, stroke=0, fill=1)
    draw_text(c, MARGIN, 270, line_a, FONT_BOLD, 40, 48, NAVY, CONTENT_W)
    draw_text(c, MARGIN, 222, line_b, FONT_BOLD, 40, 48, NAVY, CONTENT_W)
    draw_text(c, MARGIN, 150, team, FONT, 20, 28, INK, CONTENT_W)
    draw_text(c, MARGIN, 118, case, FONT, 18, 26, GRAY, CONTENT_W)
    end_slide(c)


def slide_2(c, ctx):
    """Площадка и формулировка критерия про базовый контроллер."""
    facts = ctx["facts"]
    slide_claim(
        c,
        ctx,
        2,
        "%s м до дока цеха B без ГНСС." % facts["shadow_m"],
        [
            "Площадка %s м. Четыре точки. Туман до %s м."
            % (facts["yard"], facts["fog_see"]),
            "Базовый контроллер сценарий %s не проходит." % facts["baseline"],
        ],
    )


def slide_3(c, ctx):
    """Четыре блока того, что вызывает step()."""
    begin_slide(c, 3)
    title = say(ctx, "Лидар держит позу. Зазор режет скорость.")
    caption = say(ctx, "Так вызывает step().")
    boxes = [
        ("Лидар", "держит позу"),
        ("ГНСС", "только измерение"),
        ("Путь", "сдвиг или A*"),
        ("Зазор", "режет скорость"),
    ]
    for label, detail in boxes:
        say(ctx, label)
        say(ctx, detail)
    draw_text(c, MARGIN, 470, title, FONT_BOLD, 32, 40, NAVY, CONTENT_W)
    draw_text(c, MARGIN, 420, caption, FONT, 18, 24, GRAY, CONTENT_W)
    gap = 16
    box_w = (CONTENT_W - 3 * gap) / 4.0
    box_h = 168
    y0 = 200
    for index, (label, detail) in enumerate(boxes):
        x = MARGIN + index * (box_w + gap)
        c.setFillColor(CARD)
        c.setStrokeColor(LINE)
        c.setLineWidth(1)
        c.roundRect(x, y0, box_w, box_h, 8, stroke=1, fill=1)
        c.setFillColor(ACCENT)
        c.rect(x, y0 + box_h - 6, box_w, 6, stroke=0, fill=1)
        draw_text(c, x + 16, y0 + 108, label, FONT_BOLD, 20, 26, NAVY, box_w - 32)
        draw_text(c, x + 16, y0 + 68, detail, FONT, 16, 22, INK, box_w - 32)
    end_slide(c)


def slide_4(c, ctx):
    """Отказы и то, что написано, но в step() не входит."""
    facts = ctx["facts"]
    rows = [
        "MCL: на стене %s м частицы размазываются." % facts["wall_m"],
        "ГНСС в позу не копируем: медиана %s м, док %s м."
        % (facts["gnss_median"], facts["dock"]),
        "MPC не берем: %s шагов, лимит прогона %s."
        % (
            "10⁴" if facts["steps"] == "10^4" else facts["steps"],
            facts["limit_min"],
        ),
        "CBF, Стэнли и сплайн - эталоны в tests/. В step() их нет.",
    ]
    begin_slide(c, 4)
    title = say(ctx, "Частицы, сырой ГНСС и MPC не взяли.")
    clean_rows = [say(ctx, row) for row in rows]
    draw_text(c, MARGIN, 470, title, FONT_BOLD, 32, 40, NAVY, CONTENT_W)
    y = 390
    for row in clean_rows:
        c.setFillColor(CARD)
        c.setStrokeColor(LINE)
        c.roundRect(MARGIN, y - 36, CONTENT_W, 64, 8, stroke=1, fill=1)
        c.setFillColor(ACCENT)
        c.circle(MARGIN + 28, y + 0, 5, stroke=0, fill=1)
        draw_text(c, MARGIN + 48, y - 4, row, FONT, 18, 24, INK, CONTENT_W - 70)
        y -= 82
    end_slide(c)


def slide_5(c, ctx):
    """Диапазон своих прогонов текущего кода. Открытое среднее только при том же sha."""
    span = format_score_span(ctx["own_totals"])
    title = "На этом коде свои прогоны %s. Столкновений нет." % span
    supports = ["%d прогонов s1-s5. Миссии сданы." % ctx["own_n"]]
    if ctx["same_sha"]:
        supports.append(
            "Открытые 01-04, %d прогонов, среднее %s."
            % (ctx["packet_n"], format_score(ctx["packet_mean"]))
        )
    slide_claim(c, ctx, 5, title, supports)


def slide_6(c, ctx):
    """Четыре метки демо. Экран после этого слайда - АРМ."""
    lost = ctx["lost"]
    person = ctx["yard_person"]
    cards = [
        (
            "Тень и док",
            "t=%.1f" % float(ctx["s4_arrival"]["t"]),
            "s4, seed 7, %s, %s"
            % (ctx["s4_arrival"]["status"], format_score(ctx["s4_total"])),
        ),
        (
            "Пешеход во дворе",
            "t=%.1f" % float(person["t"]),
            "04_busy_yard, d=%s, v=%s, %s, %s"
            % (
                format_score(ctx["yard_distance"]),
                format_score(person["v"]),
                person["status"],
                format_score(ctx["yard_total"]),
            ),
        ),
        (
            "Потеря ориентации",
            "t=%.1f" % lost["t0"],
            "lost, v=0, %d тактов, ход с t=%.1f" % (lost["count"], lost["resume_t"]),
        ),
        (
            "Снесенная стена",
            "t=%.1f" % float(ctx["s3_wall"]["t"]),
            "map_missing, %s" % format_score(ctx["s3_total"]),
        ),
    ]
    begin_slide(c, 6)
    title = say(ctx, "Четыре метки. Дальше экран АРМ.")
    draw_text(c, MARGIN, 492, title, FONT_BOLD, 30, 36, NAVY, CONTENT_W)
    gap = 16
    card_w = (CONTENT_W - gap) / 2.0
    card_h = 168
    top = 430
    for index, (label, when, detail) in enumerate(cards):
        say(ctx, label)
        say(ctx, when)
        say(ctx, detail)
        col = index % 2
        row = index // 2
        x = MARGIN + col * (card_w + gap)
        y = top - (row + 1) * card_h - row * gap
        c.setFillColor(CARD)
        c.setStrokeColor(LINE)
        c.setLineWidth(1)
        c.roundRect(x, y, card_w, card_h, 8, stroke=1, fill=1)
        c.setFillColor(ACCENT)
        c.rect(x, y + card_h - 6, card_w, 6, stroke=0, fill=1)
        draw_text(c, x + 18, y + card_h - 36, label, FONT, 14, 18, ACCENT, card_w - 36)
        draw_text(c, x + 18, y + card_h - 78, when, FONT_BOLD, 26, 32, NAVY, card_w - 36)
        draw_text(c, x + 18, y + 36, detail, FONT, 13, 17, INK, card_w - 36)
    end_slide(c)


def slide_7(c, ctx):
    """Ограничения, которые команда принимает."""
    facts = ctx["facts"]
    slide_claim(
        c,
        ctx,
        7,
        "Туман медленнее нарочно. Сетка поиска может промахнуться.",
        [
            "Пустой коридор в тумане не быстрее %s м/с. s5 взял %s, просел только блок эффективности."
            % (facts["fog"], format_score(ctx["s5_total"])),
            "Поиск позы только стоя, окно %s, шаг %s м. Между узлами пик может не набраться."
            % (facts["window"], facts["grid"]),
        ],
    )


def slide_8(c, ctx):
    """Сходимость кода, описания и проверки изоляции."""
    if ctx["numpy_only"]:
        deps = "В корневом requirements.txt только numpy."
    else:
        deps = "Корень: %s." % ", ".join(ctx["requirements"])
    slide_claim(
        c,
        ctx,
        8,
        "Код, APPROACH и лог говорят одно и то же.",
        [
            "amrsim check: %d нарушений. %s"
            % (ctx["check_violations"], deps),
            "Изоляция контроллера: стандартная библиотека и numpy.",
        ],
    )


def backup_title(c, text, y=470):
    """Заголовок резервного слайда. Sha здесь допустим."""
    return draw_text(c, MARGIN, y, text, FONT_BOLD, 26, 32, NAVY, CONTENT_W)


def slide_9(c, ctx):
    """Открытый пакет под тем sha, которым он снят."""
    begin_slide(c, 9)
    title = open_packet_title(
        ctx["packet_n"],
        ctx["packet_shas"],
        ctx["current_sha"],
        format_score(ctx["packet_mean"]),
    )
    subtitle = open_packet_subtitle(
        ctx["packet_shas"], ctx["current_sha"], ctx["hidden_any"]
    )
    y = backup_title(c, title, 480)
    y = draw_text(c, MARGIN, y - 6, subtitle, FONT, 16, 22, GRAY, CONTENT_W)
    rows = [("Сценарий", "Прогоны", "Мин", "Среднее", "Макс")]
    collisions_clean = True
    fatal_any = False
    for name in ctx["packet_names"]:
        reports = ctx["packet"][name]
        totals = [float(item["score"]["total"]) for item in reports]
        rows.append(
            (
                name,
                str(len(reports)),
                "%.2f" % min(totals),
                "%.2f" % (sum(totals) / len(totals)),
                "%.2f" % max(totals),
            )
        )
        for item in reports:
            if float(item["score"]["blocks"].get("collisions", 0.0)) != 0.0:
                collisions_clean = False
            if item["score"].get("fatal"):
                fatal_any = True
    y -= 16
    col_w = [CONTENT_W * share for share in (0.34, 0.16, 0.16, 0.17, 0.17)]
    row_h = 36
    for row_index, row in enumerate(rows):
        x = MARGIN
        if row_index == 0:
            c.setFillColor(NAVY)
            c.rect(MARGIN, y - row_h + 10, CONTENT_W, row_h, stroke=0, fill=1)
            color = colors.white
            font = FONT_BOLD
        else:
            color = INK
            font = FONT
        for cell, width in zip(row, col_w):
            c.setFillColor(color)
            c.setFont(font, 14)
            c.drawString(x + 8, y - 12, cell)
            x += width
        y -= row_h
    if collisions_clean and not fatal_any:
        note = "В этих отчетах наездов нет и fatal нет."
    else:
        note = "В этих отчетах есть столкновение или fatal. Смотреть таблицу прогона."
    draw_text(c, MARGIN, y - 8, note, FONT, 14, 20, INK, CONTENT_W)
    end_slide(c)


def slide_10(c, ctx):
    """О4 на текущем коде. s3 уже показан на слайде 6."""
    begin_slide(c, 10)
    y = backup_title(c, "Объезд и переплан на этом коде.", 480)
    cards = [
        (
            "s1, seed 7, t=%.1f" % float(ctx["s1_offset"]["t"]),
            "%s, %s" % (ctx["s1_offset"]["note"], format_score(ctx["s1_total"])),
            ctx["s1_log"],
        ),
        (
            "s2, seed 7, t=%.1f" % float(ctx["s2_replan"]["t"]),
            "%s, %s" % (ctx["s2_replan"]["note"], format_score(ctx["s2_total"])),
            ctx["s2_log"],
        ),
    ]
    y -= 20
    for title, detail, log_path in cards:
        c.setFillColor(CARD)
        c.setStrokeColor(LINE)
        c.roundRect(MARGIN, y - 78, CONTENT_W, 96, 8, stroke=1, fill=1)
        draw_text(c, MARGIN + 18, y - 6, title, FONT_BOLD, 20, 26, NAVY, CONTENT_W - 36)
        draw_text(c, MARGIN + 18, y - 36, detail, FONT, 16, 22, INK, CONTENT_W - 36)
        draw_text(c, MARGIN + 18, y - 60, log_path, FONT, 11, 14, GRAY, CONTENT_W - 36)
        y -= 114
    draw_text(
        c,
        MARGIN,
        y - 4,
        "Снесенная стена s3, t=%.1f, на слайде 6." % float(ctx["s3_wall"]["t"]),
        FONT,
        16,
        22,
        INK,
        CONTENT_W,
    )
    end_slide(c)


def slide_11(c, ctx):
    """Маршрут по экранам АРМ. ctx не несет чисел, аргумент сохранен для единообразия."""
    del ctx
    begin_slide(c, 11)
    backup_title(c, "АРМ: просмотр, рейсы, события, запуск.", 480)
    left = [
        "Просмотр: пауза и перемотка",
        "Карта, поза и pose_est",
        "Пешеходы по времени",
        "Миссии: журнал рейсов",
    ]
    right = [
        "Статус и note: причина остановки",
        "Инциденты: клик открывает такт",
        "Экспорт CSV на странице инцидентов",
        "Дашборд: «Запустить симуляцию»",
    ]
    y = 400
    for item in left:
        draw_text(c, MARGIN, y, item, FONT, 16, 22, INK, CONTENT_W / 2 - 20)
        y -= 48
    y = 400
    for item in right:
        draw_text(c, MARGIN + CONTENT_W / 2, y, item, FONT, 16, 22, INK, CONTENT_W / 2 - 8)
        y -= 48
    draw_text(
        c,
        MARGIN,
        120,
        "Потеря ориентации открывается адресом s4b_shadow_lane_lost_seed1. Пункт s4b в списке - seed 7, там lost нет.",
        FONT,
        14,
        20,
        GRAY,
        CONTENT_W,
    )
    end_slide(c)


def slide_12(c, ctx):
    """Воспроизводимость. Число тестов считается по tests/."""
    begin_slide(c, 12)
    y = backup_title(c, "Проверка повторяется из README.", 480)
    lines = [
        "sha controller.py: %s" % ctx["current_sha"],
        "pytest в tests/: %d" % ctx["pytest_count"],
        "amrsim check: %d нарушений, %d предупреждений"
        % (ctx["check_violations"], ctx["check_warnings"]),
        "requirements.txt: %s" % "; ".join(ctx["requirements"]),
        "PYTHONPATH=amrsim-participants python -m amrsim check team_dreamteam_4_0",
        "PYTHONPATH=amrsim-participants python -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json",
    ]
    y -= 8
    for line in lines:
        y = draw_text(c, MARGIN, y, line, FONT, 13, 18, INK, CONTENT_W)
        y -= 10
    end_slide(c)


def register_fonts():
    """Кириллические шрифты системы."""
    if not FONT_PATH.exists():
        raise SystemExit("Не найден шрифт: %s" % FONT_PATH)
    pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))
    bold = FONT_BOLD_PATH if FONT_BOLD_PATH.exists() else FONT_PATH
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))


def main():
    """Собрать presentation.pdf."""
    register_fonts()
    ctx = build_context()
    c = canvas.Canvas(str(OUT_PATH), pagesize=(PAGE_W, PAGE_H), invariant=1)
    c.setTitle("Безопасный маршрут - Dreamteam 4.0")
    c.setAuthor("Dreamteam 4.0")
    c.setSubject("Защита контроллера AMR, схема amr-1.0")
    c.setCreator("scripts/make_presentation.py")
    slide_1(c, ctx)
    slide_2(c, ctx)
    slide_3(c, ctx)
    slide_4(c, ctx)
    slide_5(c, ctx)
    slide_6(c, ctx)
    slide_7(c, ctx)
    slide_8(c, ctx)
    slide_9(c, ctx)
    slide_10(c, ctx)
    slide_11(c, ctx)
    slide_12(c, ctx)
    # showPage() в каждом слайде уже открыл следующую пустую страницу.
    # Сохраняем только закрытые: reportlab пишет текущую пустую, если на ней
    # что-то есть. Пустую не рисуем, но getPageNumber после 12 showPage равен 13.
    if c.getPageNumber() != TOTAL_SLIDES + 1:
        raise SystemExit("Ожидалось %d слайдов" % TOTAL_SLIDES)
    c.save()
    print("Собрано: %s" % OUT_PATH)
    print("Страниц: %d" % TOTAL_SLIDES)
    for line in ctx["spoken"]:
        print("SAY %s" % line)


if __name__ == "__main__":
    main()
