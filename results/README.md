# Результаты и приёмка (сдача)

Все отчёты в этой папке пересняты на финальном дереве финальным контроллером
`team_dreamteam_4_0/controller.py`, sha256 `2f4a721eafcfb6ed` (первые 16 hex-символов,
как их пишет amrsim). Команда прогона одного сценария:

```bash
PYTHONPATH=amrsim-participants uv run python -m amrsim run <scenario> \
  --controller team_dreamteam_4_0/controller.py --seed <N> --report <файл> --log <файл.jsonl>
```

Состав:

| Файл / папка | Что это |
| --- | --- |
| `team_dreamteam_4_0_01..04_*.json`, `team_summary.json` | прогон через `scripts/eval.py` (репозиторный харнесс), seed 7 |
| `seed_packet/<сценарий>_<seed>.json` | пакет приёмки: 4 сценария x seed 1,2,3,7,11,21,42 = 28 прогонов |
| `seed_packet/01e_clear_easy_7.json`, `seed_packet/02e_gnss_shadow_easy_7.json` | лёгкие открытые сценарии, seed 7: отчёт есть на каждый сценарий из `scenarios/`, чтобы ARM не показывал `hasReport = false` |
| `table.csv`, `table_summary.csv` | тот же пакет через `python -m amrsim batch teams <4 сценария> --seeds 1,2,3,7,11,21,42 --out results/table.csv` |
| `table_runs/reports/team_dreamteam_4_0__*.json` | те же 28 прогонов batch (имя команды берётся из ссылки `teams/team_dreamteam_4_0`); логи в `table_runs/logs/` в git не идут |
| `own_scenarios/*.json` | свои сценарии из `scenarios/s1..s5`, seed 7 |
| `own_scenarios/s4b_shadow_lane_lost_seed1.json` | контрольный прогон s4b на seed 1: потеря ориентации и восстановление |
| `own_scenarios/logs/*.jsonl` | покадровые логи своих сценариев (seed 7) и s4b seed 1 |
| `own_scenarios/moments.json`, `own_scenarios/moments.md` | моменты для критериев О2 и О4: сценарий, seed, t, статус, note, файл лога |
| `arm/arm_run_01_clear_seed7_*.json`/`*.jsonl`/`*.csv`/`*.txt` | подтверждение О4 через АРМ: прогон из `POST /api/run` и CSV из `GET /api/export/csv` (сценарий `01_clear`, seed 7) |
| `oracle_<сценарий>.json` | потолок: baseline с истиной (`--cheat`), seed 7 |
| `results/ALTERNATIVES.md` | инженерное обоснование подхода, анализ альтернатив и компромиссов (критерий О1) |
| `baseline_*.json` | исходные числа baseline из постановки (не перезаписывались) |

## Пакет seed x 01-04 (28 прогонов)

Агрегаты по 28 отчётам основного пакета `results/seed_packet` (тот же контроллер):

| Сценарий | total min | mean | max | safety min | pose min | доставлено | fatal | collisions | эпизоды |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01_clear | 99.99 | 100.00 | 100.00 | 25.0 | 10 | 7/7 прогонов | нет | 0 | 0 |
| 02_gnss_shadow | 100.00 | 100.00 | 100.00 | 25.0 | 10 | 7/7 | нет | 0 | 0 |
| 03_fog_snow | 97.69 | 98.34 | 98.76 | 25.0 | 10 | 7/7 | нет | 0 | 0 |
| 04_busy_yard | 97.96 | 98.55 | 98.90 | 25.0 | 10 | 7/7 | нет | 0 | 0 |

В каждом из 28 отчётов `counted = true`, `fatal = false`, `collisions = 0`, `sandbox_violations`
пустой, `end_reason = missions_done`. `results/table_summary.csv` даёт
`team_dreamteam_4_0, OK, 28, 99.22, , 99.22`.

### Пороги plan/05:84-92

| Порог | Факт |
| --- | --- |
| каждый прогон `counted=true`, все миссии `delivered` | выполнено: 28/28 прогонов, 49 миссий |
| `fatal=false`, `collisions = 0` | выполнено |
| 02: док B, `pose = 10` | выполнено на всех 7 seed (total 100.00) |
| 03: `safety >= 23`, оба плеча в дедлайне | выполнено: safety 25.0, все плечи в дедлайне |
| 04: нет контакта с поддоном/контейнером, человек не классифицирован стеной | выполнено: 0 контактов, 0 эпизодов `person_classified_wall` |
| среднее по четырём сценариям `>= 95` | выполнено: по seed 98.99 - 99.27, минимум на seed 2 |
| `sandbox_violations` пусто, `check` = OK | выполнено: `check team` 0 violations / 0 warnings |
| `step_time_ms.max` далеко от бюджета 600 с | выполнено: десятки мс на редком тике, wall 2-9 с на прогон |

## Сравнение с оракулом (plan/05:94-100)

| Сценарий | оракул `--cheat` | наша команда (seed 7) | отставание |
| --- | --- | --- | --- |
| 01_clear | 99.48 | 100.00 | -0.52 (мы выше) |
| 02_gnss_shadow | 100.00 | 100.00 | 0.00 |
| 03_fog_snow | 99.02 | 98.66 | +0.36 |
| 04_busy_yard | 98.10 | 98.87 | -0.77 (мы выше) |

Отставание нигде не превышает 0.36 балла при пороге плана 3 балла. Средний балл по открытым сценариям: 99.38; pose 10/10 везде, 0 штрафных эпизодов.

## Свои сценарии (seed 7)

| Сценарий | total | pose | safety | missions | момент для сдачи |
| --- | --- | --- | --- | --- | --- |
| `s1_pallet_2m` | 98.84 | 10 | 25.0 | 2/2 | t=111.9, note `offset dy=-0.4` (объезд, О4) |
| `s2_container_block` | 100.00 | 10 | 25.0 | 1/1 | t=148.2, note `replan` (перепланирование, О4) |
| `s3_wall_removed` | 100.00 | 10 | 25.0 | 1/1 | t=9.8, note `map_missing` (расхождение карты, О4) |
| `s4_shadow_start_charger` | 100.00 | 10 | 25.0 | 1/1 | t=48.8, статус `arrived`, note `dock` |
| `s4b_shadow_lane_lost` | 100.00 | 10 | 25.0 | 1/1 | на seed 7 потеря не возникает; контроль - seed 1 |
| `s5_fog_inattentive` | 99.27 | 10 | 25.0 | 2/2 | t=40.0 `fog_clear`; t=87.0 `stop_person d=0.7` (О2) |

Прогон `s4b_shadow_lane_lost` на seed 1: total 99.3, доставка 1/1, collisions 0, fatal нет.
Потеря ориентации: note `lost s_lat=0.0 map_extra` с t=26.0, статус `lost` с t=27.2 (v = 0),
восстановление с t=28.0. Лог лежит в `own_scenarios/logs/s4b_shadow_lane_lost_seed1.jsonl`.

Во всех прогонах: `collisions = 0`, `fatal = false`, ноль штрафных эпизодов,
`sandbox_violations` пустой, `max_hold_dist < 0.2` м (порог plan/05:64). Полная таблица моментов
с фактическими t, статусами и note - в `own_scenarios/moments.md` и `own_scenarios/moments.json`.

## Матрица подтверждения дополнительных возможностей (Критерий О4 - 10 баллов)

По официальному регламенту хакатона каждый пункт критерия О4 подтвержден сценарием, таймкодом в логе, файлом отчета и местом в кодовой базе:

| Дополнительная возможность О4 | Сценарий проверки | Момент / эпизод в логе | Файл отчета и лога | Реализация в кодовой базе |
| :--- | :--- | :--- | :--- | :--- |
| **1. Объезд оставленного предмета** | `s1_pallet_2m.json` (seed 7) | $t=111.9$ с, `status=moving`, note `offset dy=-0.4` | `own_scenarios/s1_pallet_2m.json`, лог `logs/s1_pallet_2m.jsonl` | [follower.py](file:///Users/yegor/doc-1790342627/team_dreamteam_4_0/route/follower.py) (метод `_find_lateral_shift`) |
| **2. Перепланирование маршрута** | `s2_container_block.json` (seed 7) | $t=148.2$ с, `status=moving`, note `replan` | `own_scenarios/s2_container_block.json`, лог `logs/s2_container_block.jsonl` | [astar.py](file:///Users/yegor/doc-1790342627/team_dreamteam_4_0/route/astar.py) (`astar_search` в объезд заблокированного проезда) |
| **3. Обнаружение расхождения карты** | `s3_wall_removed.json` (seed 7) | $t=9.8$ с, `status=moving`, note `map_missing` | `own_scenarios/s3_wall_removed.json`, лог `logs/s3_wall_removed.jsonl` | [perception.py](file:///Users/yegor/doc-1790342627/team_dreamteam_4_0/perceive/perception.py) (детекция отсутствующих стен и контейнеров) |
| **4. Запуск прогона из АРМ с показом** | `01_clear.json` (seed 7) | Вкладка Runner: `POST /api/run`, стриминг логов в терминал, `exitCode 0`, score 100.00 | `results/arm/arm_run_01_clear_seed7_report.json`, лог `arm_run_01_clear_seed7_ticks.jsonl`, ответ `arm_run_01_clear_seed7_api_response.json` | [RunnerPage.tsx](file:///Users/yegor/doc-1790342627/arm/frontend/src/pages/RunnerPage.tsx), [server.py](file:///Users/yegor/doc-1790342627/arm/server.py) (`POST /api/run`) |
| **5. Экспорт журнала в CSV** | `01_clear.json` (seed 7) | Вкладка Episodes: `GET /api/export/csv`, все поля инцидентов | `results/arm/arm_export_episodes_01_clear_seed7.csv` (4 эпизода) | [server.py](file:///Users/yegor/doc-1790342627/arm/server.py) (`GET /api/export/csv`) |
| **6. Собственные сценарии и автотесты** | 5 сценариев (`s1`..`s5`) + 260 тестов | Сценарии `scenarios/s1`..`s5`; 260 тестов `uv run pytest -v` (100% passed) | `results/own_scenarios/`, `tests/` | `tests/test_route.py`, `test_safety.py`, `test_localize.py`, `test_perceive.py` |

## Тесты

`tests/` (260 тестов, `uv run pytest`): восемь обязательных поведенческих сценариев
plan/05:108-115 покрыты поимённо, плюс тесты на тиры σ, подтверждение треков, снежные
фантомы, классы объектов, A*, зоны, тормозной профиль и контракт эпизодов ARM.
Контроллер тесты не импортирует. Фронтенд АРМ: 89 тестов Vitest и чистый `tsc --noEmit`.

## Честно о границах

- **03_fog_snow ниже baseline**: это цена тиров самого плана - в тумане 0.9 м/с на пустом
  коридоре и 0.35 м/с у кластера, зона 0.95 и человеческие лимиты. Доставка и дедлайны
  выполнены, safety 25.0, среднее по сценариям выше порога 95.
- **Компромиссы, отличающиеся от буквы плана** (все в `APPROACH.md`): порог замедления
  перед человеком сдвинут на 0.28·v (до 0.4 м); предмет подтверждается 1.5-2 с вместо 1 с;
  упор колёс - 5 см за 5 тиков вместо 2 см; стоп в коридоре обнуляет `v`, но разрешает `w`.
- **Поиск позы по сетке не гарантирован**: шаг сетки 0.5 м при допуске инлайнера 0.25 м -
  если смещение попало между узлами, пик не набирает инлайнеров и платформа остаётся стоять.
  На требуемых seed 1,2,3,7,11,21,42 сценарий `s4b` доставлен; на seed 7 потери нет вовсе,
  потеря показана на seed 1.
- **Открытые прогоны без штрафных эпизодов**: перечень эпизодов пуст, поэтому в журнале
  эпизодов ARM вехи миссий помечены отдельно (`source = "mission"`) и не несут цены -40.
- **Скрытые сценарии не измерялись**: тиры σ (0.4/0.6 м/с) на открытых прогонах не
  срабатывают (σ поперёк не выше 0.21, σ вдоль не выше 0.75) и включены по плану
  plan/02:137-139; на скрытых картах они могут стоить времени, но не безопасности.
