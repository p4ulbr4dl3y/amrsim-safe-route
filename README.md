# Безопасный маршрут — контроллер AMR (amr-sim 0.2, схема amr-1.0)

Кейс «Безопасный маршрут»: автономная платформа возит грузы между складом,
цехами A/B и зарядной по проездам и не должна задевать людей, предметы и стены —
в том числе в тени ГНСС, тумане и снеге. Этот репозиторий — контроллер участника:
каждый тик он получает `obs` (одометрия, IMU, лидар, ГНСС, миссия) и возвращает
`v`, `w`, `status`, `pose_est`, `note` по схеме amr-1.0.

Контроллер собран из модулей только на стандартной библиотеке и numpy:
`localize.py` (скан-матч стен, ГНСС-гейт, калибровка масштаба, dock-snap),
`perceive.py` (кластеры и треки препятствий в чистой одометрии),
`route.py` (pure pursuit, боковой сдвиг, локальный A*, зоны скорости),
`safety.py` (зазоры, коридор, estop, статусы), `geom.py` (геометрия),
`controller.py` (сборка и порядок вызовов). Кратко о решениях и ограничениях —
в `team/APPROACH.md`.

## Требования

- Python >= 3.10 (см. `pyproject.toml`, `requires-python = ">=3.10"`);
- только `numpy` (одна строка в `team/requirements.txt`, `numpy>=1.24.0`);
- интерпретатор `amrsim` лежит в `amrsim-participants/` и запускается через
  `PYTHONPATH=amrsim-participants`; кроме numpy он ничего не требует.

## Установка в чистом окружении

Из корня репозитория:

```bash
python -m venv .venv
.venv/bin/pip install -r team/requirements.txt
```

То же самое без файла требований: `.venv/bin/pip install numpy`.

## Проверка правил изоляции

```bash
PYTHONPATH=amrsim-participants .venv/bin/python -m amrsim check team
```

Ожидаемый результат: `check team: 0 violation(s) or error(s), 0 warning(s)` /
`result: OK`.

## Прогон одного сценария

```bash
PYTHONPATH=amrsim-participants .venv/bin/python -m amrsim run \
  amrsim-participants/scenarios/01_clear.json \
  --controller team/controller.py --seed 7 --report out/01.json
```

Отчёт по сценарию появится в `out/01.json`. Полезно добавить `--log out/01.jsonl`,
чтобы получить покадровый журнал. Флаг `--cheat` (истинная поза) — только для
локального сравнения с оракулом, в зачёт он не идёт.

## Пакет прогонов по seed

```bash
PYTHONPATH=amrsim-participants .venv/bin/python -m amrsim batch \
  team amrsim-participants/scenarios \
  --seeds 1,2,3,7,11,21,42 --out out/table.csv
```

`batch` берёт каталог `team` как команду (в нём есть `controller.py`), гоняет все
`*.json` из каталога сценариев (включая учебные `01e`/`02e`) на каждом seed и
пишет таблицу в `out/table.csv` и сводку в `out/table_summary.csv`. Один seed
можно проверить так: `--seeds 7`.

## Тесты

```bash
.venv/bin/python -m unittest discover -s tests
```

`tests/` контроллер не импортирует; тесты написаны на stdlib и numpy и проверяют
поведение модулей (локализация, маршрут, безопасность, восприятие).

## Состав репозитория

```
team/
  controller.py     # точка входа: порядок predict → scan-match → GNSS → perception → route → safety
  geom.py           # геометрия: отрезки, raycast, AABB, полигоны
  localize.py       # локализация: фильтр, скан-матч, ГНСС, масштаб, dock-snap, lost
  perceive.py       # восприятие: кластеры, треки, классы, map_missing/map_extra
  route.py          # маршрут: pure pursuit, сдвиг, A*, зоны скорости
  safety.py         # безопасность: зазоры, коридор, estop, статусы и note
  APPROACH.md       # 15-25 строк о локализации, маршруте, безопасности и ограничениях
  requirements.txt  # одна строка: numpy
  scenarios/        # свои проверки О4 (s1_pallet_2m, s2_container_block, s3_wall_removed,
                    #   s4_shadow_start_charger, s5_fog_inattentive)
tests/              # unittest: test_geom, test_localize, test_perceive, test_route, test_safety
results/            # отчёты score: baseline_*.json и team_*.json по сценариям 01-04
amrsim-participants/  # SDK симулятора amr-sim 0.2 (вне команды, только для запуска)
out/                # выход прогонов: --report, --log, таблицы batch (в .gitignore)
```

Свои сценарии из `team/scenarios/` запускаются тем же `amrsim run` с
`--controller team/controller.py`; контроллер их не читает и по именам файлов не
ветвится. Отчёты и таблицы складываются в `results/` и `out/`.
