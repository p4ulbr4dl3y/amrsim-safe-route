# Безопасный маршрут — контроллер AMR (Dreamteam 4.0)

Кейс «Безопасный маршрут»: автономная платформа возит грузы между складом,
цехами A/B и зарядной по проездам и не должна задевать людей, предметы и стены —
в том числе в тени ГНСС, тумане и снеге. Этот репозиторий — контроллер участника:
каждый тик он получает `obs` (одометрия, IMU, лидар, ГНСС, миссия) и возвращает
`v`, `w`, `status`, `pose_est`, `note` по схеме amr-1.0.

Контроллер собран из модулей строго на стандартной библиотеке и numpy:
`localize.py` (скан-матч стен, ГНСС-гейт, калибровка масштаба, dock-snap),
`perceive.py` (кластеры и треки препятствий в чистой одометрии),
`route.py` (pure pursuit, боковой сдвиг, локальный A*, зоны скорости),
`safety.py` (зазоры, коридор, estop, статусы), `geom.py` (геометрия),
`controller.py` (сборка и порядок вызовов). Описание подхода и обоснование решений —
в [`APPROACH.md`](APPROACH.md) и [`team_dreamteam_4_0/APPROACH.md`](team_dreamteam_4_0/APPROACH.md).

## Требования

- Python >= 3.10 (см. `pyproject.toml`, `requires-python = ">=3.10"`);
- только `numpy` (в `requirements.txt` и `team_dreamteam_4_0/requirements.txt`: `numpy>=1.24.0`);
- симулятор `amrsim` лежит в `amrsim-participants/` и запускается через
  `PYTHONPATH=amrsim-participants`; кроме numpy он ничего не требует.

## Установка в чистом окружении

Из корня репозитория:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Или через `uv`:
```bash
uv sync
```

## Проверка правил изоляции (Критерий Т3)

```bash
PYTHONPATH=amrsim-participants python -m amrsim check team_dreamteam_4_0
```

Ожидаемый результат:
```
check team_dreamteam_4_0: 0 violation(s) or error(s), 0 warning(s)
result: OK
```

## Прогон одного сценария

```bash
PYTHONPATH=amrsim-participants python -m amrsim run \
  scenarios/01_clear.json \
  --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json
```

Отчёт по сценарию появится в `out/01.json`. Флаг `--log out/01.jsonl` формирует покадровый журнал тиков для АРМ.

## Пакет прогонов по seed

```bash
PYTHONPATH=amrsim-participants python -m amrsim batch \
  teams scenarios \
  --seeds 1,2,3,7,11,21,42 --out out/table.csv
```

## Тесты и линтеры

```bash
uv run ruff check       # Быстрый линтинг Python
uv run pytest -v        # 237 автоматических тестов (алгоритмы, сервер, оценка)
```

## АРМ Оператора (Критерий О3 — 15 баллов)

Веб-станция оператора с Server-Driven UI, 2D Canvas картой и Replay Studio.

1. Запуск сервера АРМ (Python stdlib, раздает собранный UI из `arm/frontend/dist`):
```bash
python arm/server.py --port 8000
```
Открыть в браузере: `http://localhost:8000`

2. Разработка и тестирование фронтенда:
```bash
cd arm/frontend
npm install
npm run lint    # Проверка типов TypeScript (tsc --noEmit)
npm test        # 87 тестов Vitest
npm run build   # Сборка SPA в arm/frontend/dist
```

## Состав репозитория

```
team_dreamteam_4_0/    # Модули алгоритма контроллера (критерии Т1, Т2, Т4, Т5)
  controller.py        # Точка входа: порядок predict → scan-match → GNSS → perception → route → safety
  geom.py              # Геометрия: отрезки, raycast, AABB, полигоны
  localize.py          # Локализация: фильтр, скан-матч, ГНСС, масштаб, dock-snap, lost
  perceive.py          # Восприятие: кластеры, треки, классы, map_missing/map_extra
  route.py             # Маршрут: pure pursuit, сдвиг, A*, зоны скорости
  safety.py            # Безопасность: зазоры, коридор, estop, статусы и note
  APPROACH.md          # 26 строк о локализации, маршруте, безопасности и ограничениях
  requirements.txt     # Одна строка: numpy
  scenarios/           # Свои проверки О4 (s1..s5)
arm/                   # Рабочее место оператора (критерий О3)
  server.py            # Zero-dependency HTTP/API сервер
  requirements.txt     # Зависимости АРМ
  README.md            # Инструкция запуска АРМ
  frontend/            # React + Vite + Tailwind + Canvas 2D + KaTeX
scenarios/             # Открытые (01..04) и кастомные сценарии (s1..s5, критерий О4)
tests/                 # 237 модульных тестов: алгоритмы, сервер, метрики (критерий Т5)
results/               # Отчёты score: baseline_*.json и team_*.json по сценариям 01-04
APPROACH.md            # Корневой файл обоснования подхода (критерии Т3, О1)
presentation.pdf       # Презентация к защите до 12 слайдов (критерий О5)
.github/workflows/ci.yml # Автоматический CI (тесты, линтеры, сборка, симуляция)
```
