#!/usr/bin/env bash
# Защитный скрипт проверки отсутствия регрессий перед git push
set -euo pipefail

echo "=== [1/4] Проверка стиля и качества кода (ruff) ==="
uv run ruff check

echo "=== [2/4] Проверка изоляции и ограничений ТЗ Т3 (amrsim check) ==="
PYTHONPATH=amrsim-participants uv run python -m amrsim check team_dreamteam_4_0

echo "=== [3/4] Модульные и интеграционные тесты (pytest) ==="
uv run pytest -q

echo "=== [4/4] Контроль регрессий сценариев бенчмарка (eval check-regression) ==="
uv run python scripts/eval.py --scenarios 01_clear 02_gnss_shadow s4b_shadow_lane_lost --check-regression

echo "=== Все проверки успешно пройдены. Регрессий нет! ==="
