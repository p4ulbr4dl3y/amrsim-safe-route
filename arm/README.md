# Рабочее место оператора (АРМ) - Dreamteam 4.0

Веб-станция оператора для мониторинга, разбора телеметрии, разбора инцидентов и запуска симуляций (критерий О3 - 15 баллов).

## Быстрый запуск (1 команда)

Из корня репозитория:
```bash
uv run python arm/server.py --port 8000
```
Или в стандартном Python окружении:
```bash
python3 arm/server.py --port 8000
```
Затем открыть в браузере: `http://localhost:8000`

> **Примечание:** Сервер написан строго на стандартной библиотеке Python (`http.server` + `json`) без сторонних зависимостей и автоматически раздает предсобранный SPA-интерфейс из каталога `arm/frontend/dist`.
>
> Предсобранный `arm/frontend/dist` входит в репозиторий, поэтому чистый клон отдает интерфейс сразу, без шага `npm run build`. Если вы меняли исходники фронтенда, пересоберите SPA (`cd arm/frontend && npm install && npm run build`) и закоммитьте обновленный `dist`.
 
## Опциональный запуск в Docker

Запуск веб-станции АРМ и симулятора через Docker Compose:
```bash
docker compose up --build
```
Интерфейс доступен по адресу: `http://localhost:8000`.

Команды симулятора и проверка изоляции Т3 в контейнере:
```bash
docker compose run --rm arm python -m amrsim check team_dreamteam_4_0
docker compose run --rm arm python -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report /app/out/01.json
```

## Возможности АРМ (Критерий О3):
- **Dashboard**: сводная статистика KPI, статус выполнения заданий, целевая функция, анализ штрафов и загрузка сценариев;
- **Replay**: интерактивный плеер тиков с 2D Canvas картой площадки, положением платформы, пешеходами, шлейфом пути, отрисовкой препятствий, паллет и контейнеров, а также переключением слоев лидара;
- **Синхронизация сценариев**: сквозная синхронизация выбранного сценария между всеми разделами (Dashboard, Replay, Episodes, Missions, Analytics, Runner) и хэшем URL;
- **Episodes**: журнал эпизодов нарушений с фильтрацией, формулами LaTeX и экспортом отчета в CSV;
- **Missions**: журнал рейсов с контролем дедлайнов и погрешности позиционирования у целевых доков;
- **Analytics**: радарный график по 6 блокам оценки, аудит песочницы Т3 и вычислительного бюджета времени;
- **Runner**: запуск симуляций `amrsim` в реальном времени с выводом логов в веб-терминал;
- **Документация API и OpenAPI**: встроенный интерактивный Swagger UI и спецификация схемы `amr-1.0`.

## Модульная архитектура сервера:
- `arm/core/`: базовые модули конфигурации и исполнения:
  - `config.py`: константы путей, лимиты кэшей `BoundedCache`, метаданные сценариев `SCENARIO_META`, формулы и правила штрафов;
  - `runner.py`: потокобезопасный вызов CLI симулятора `amrsim`, обнаружение интерпретатора Python, форматирование логов выполнения;
- `arm/services/`: бизнес-логика и формирование моделей представления:
  - `storage.py`: чтение и кэширование отчетов (`out/`, `results/`), потоковый парсинг логов тиков `.jsonl`, сохранение пользовательских сценариев в `scenarios/`;
  - `view_models.py`: трансформация сырой телеметрии и отчетов в структуры Server-Driven UI (Dashboard, Replay, Episodes, Missions, Analytics), извлечение полигонов стен, зон, препятствий, паллет и контейнеров;
- `arm/transport/`: сетевой слой и протокол обмена:
  - `handler.py`: класс `AMRServerHandler` на базе `SimpleHTTPRequestHandler`, CORS заголовки, маршрутизация GET/POST, экспорт эпизодов в CSV с UTF-8 BOM;
  - `docs.py`: схема OpenAPI 3.0 (`/api/openapi.json`) и встраиваемый HTML Swagger UI (`/docs`);
- `arm/server.py`: фасадный модуль и точка входа сервера, связывающая все подсистемы и поддерживающая запуск через CLI.

## Спецификация API и интеграция:
Сервер оператора реализует архитектуру Server-Driven UI и предоставляет документированные конечные точки:
- интерактивная документация: `http://localhost:8000/docs` (Swagger UI);
- спецификация OpenAPI 3.0: `http://localhost:8000/api/openapi.json`;
- список доступных сценариев: `GET /api/scenarios`;
- модель представления дашборда: `GET /api/ui/dashboard?scenario=<id>`;
- модель представления плеера: `GET /api/ui/replay?scenario=<id>&seed=<seed>`;
- модель представления эпизодов: `GET /api/ui/episodes?scenario=<id>`;
- модель представления миссий: `GET /api/ui/missions?scenario=<id>`;
- модель представления аналитики: `GET /api/ui/analytics?scenario=<id>`;
- запуск автономной симуляции: `POST /api/run`;
- сохранение сценария: `POST /api/scenarios/save`;
- экспорт инцидентов в CSV: `GET /api/export/csv?scenario=<id>`;
- отчет симуляции сценария: `GET /api/report?scenario=<id>`;
- такты лога симуляции: `GET /api/ticks?scenario=<id>`.

Схема выходных данных такта управления `amr-1.0`:
- `v`: линейная скорость платформы, м/с (диапазон 0.0 - 1.5);
- `w`: угловая скорость платформы, рад/с (диапазон -1.0 - 1.0);
- `status`: статус платформы (`moving`, `waiting`, `arrived`, `lost`, `estop`);
- `pose_est`: оценка глобальной позы платформы `[x, y, yaw]`;
- `note`: строка заметок телеметрии и состояний подсистем безопасности.

## Разработка и тестирование:
- тесты бэкенда (90 тестов `tests/test_server.py`, 100% green):
  ```bash
  uv run pytest tests/test_server.py -v
  ```
- тесты фронтенда (8 тест-файлов, 69 тестов Vitest, 100% green):
  ```bash
  cd arm/frontend
  npm install
  npm run dev     # Режим локальной разработки
  npm test        # 69 автоматических тестов Vitest (100% passed)
  npm run lint    # Проверка типов TypeScript (tsc --noEmit)
  npm run build   # Сборка SPA в arm/frontend/dist
  ```
