# АРМ: подтверждение прогоном (критерий О4)

Артефакты подтверждают два пункта О4, для которых раньше не было отчета или лога
в `results/`: запуск задания из АРМ (`POST /api/run`) и экспорт журнала в CSV
(`GET /api/export/csv`).

## Сценарий и сид

- Сценарий: `scenarios/01_clear.json` (ясная погода, штатная доставка склад - цех A - склад).
- Seed: `7`.
- Контроллер: `team_dreamteam_4_0/controller.py`, `--cheat` выключен (`cheatPose = false`).
- Сервер АРМ: `python3 arm/server.py --port 8231 --host 127.0.0.1` на системном Python 3.9.6,
  то есть запуск задания из вкладки Runner больше не падает с `exitCode 2`
  (интерпретатор для симулятора берется из `uv run --project`, см. `arm/server.py`,
  `resolve_python_command`).

## Файлы

| Файл | Что это |
| --- | --- |
| `arm_run_01_clear_seed7_transcript.txt` | покадровая расшифровка проверки: HTTP-коды `GET /`, `/api/scenarios`, `/api/ui/replay`, `POST /api/run`, `/api/export/csv` и итог `exitCode 0`, score 100.00 |
| `arm_run_01_clear_seed7_api_response.json` | полный JSON-ответ `POST /api/run` (логи терминала, `exitCode`, `score`, пути отчет/лог) |
| `arm_run_01_clear_seed7_report.json` | отчет прогона, снятый АРМ в `out/01_clear.json` (score 100.00, блоки, миссии, песочница) |
| `arm_run_01_clear_seed7_ticks.jsonl` | покадровый лог телеметрии прогона (JSONL) |
| `arm_export_episodes_01_clear_seed7.csv` | журнал эпизодов, скачанный по `GET /api/export/csv?scenario=01_clear` (UTF-8 BOM, все поля инцидентов) |

## Результат прогона

- `exitCode = 0`, `score.total = 100.00` (delivery 40.0, efficiency 15.0, safety 25.0, rules 10.0, pose 10.0, collisions 0.0).
- 3107 тиков, `end_reason = missions_done`, обе миссии `delivered`, `fatal = false`,
  `sandbox_violations` пустой.
- CSV содержит 5 строк (заголовок и 4 эпизода): старт и доставка m1, старт и доставка m2,
  плюс защитная остановка перед пешеходом на `t = 57.8` с.

## Воспроизведение

```bash
python3 arm/server.py --port 8231 --host 127.0.0.1
curl -s -X POST http://127.0.0.1:8231/api/run \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"01_clear","controller":"team_dreamteam_4_0/controller.py","seed":7,"cheatPose":false}'
curl -s "http://127.0.0.1:8231/api/export/csv?scenario=01_clear"
```