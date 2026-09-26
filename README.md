# Безопасный маршрут - контроллер платформы Dreamteam 4.0

Ключевые свойства архитектуры:
- контроллер участника: пакет [`team_dreamteam_4_0/`](team_dreamteam_4_0/) только на стандартной библиотеке Python и NumPy;
- схема обмена: контракт `amr-1.0` (`v`, `w`, `status`, `pose_est`, `note`);
- живой демо-стенд АРМ: **https://state3407.space/amr/** (плеер тиков, карта 2D Canvas, разбор инцидентов, запуск симуляций);
- интерактивная документация API АРМ: **https://state3407.space/amr/docs**.

---

## Быстрая проверка за 60 секунд

Запуск верификации любым удобным способом:

```bash
# Способ 1: через Make (автоматически выбирает uv или стандартный python3):
make verify          # проверка изоляции Т3, модульные тесты Т5 и линтер
make sim             # запуск симуляции контрольного сценария 01_clear

# Способ 2: стандартный pip и venv (без uv):
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=amrsim-participants python -m amrsim check team_dreamteam_4_0
pytest -v

# Способ 3: через менеджер uv (macOS / Linux):
uv sync
PYTHONPATH=amrsim-participants uv run python -m amrsim check team_dreamteam_4_0
uv run pytest -v

# Способ 4: через uv на Windows (PowerShell):
uv sync
$env:PYTHONPATH="amrsim-participants"; uv run python -m amrsim check team_dreamteam_4_0
uv run pytest -v
```

Веб-станция оператора АРМ (критерий О3):
- онлайн без установки: **https://state3407.space/amr/**;
- локальный запуск: `make arm` или `python arm/server.py --port 8000`.

---

## 1. Проверка изоляции и окружения (Критерий Т3)

По регламенту соревнований контроллер не использует внешних библиотек оптимизации, сетевых вызовов и записи на диск во время работы:
- версия Python >= 3.10;
- единственная зависимость: `numpy>=1.24.0` в корневом [`requirements.txt`](requirements.txt) и в [`team_dreamteam_4_0/requirements.txt`](team_dreamteam_4_0/requirements.txt).

Подготовка окружения:
```bash
uv sync
```
*Либо через стандартный pip: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`.*

### Валидация правил изоляции пакета команды:
```bash
PYTHONPATH=amrsim-participants uv run python -m amrsim check team_dreamteam_4_0
```
На Windows (PowerShell):
```powershell
$env:PYTHONPATH="amrsim-participants"; uv run python -m amrsim check team_dreamteam_4_0
```
Ожидаемый результат:
```text
check team_dreamteam_4_0: 0 violation(s) or error(s), 0 warning(s)
result: OK
```

---

## 2. Результаты на открытых и собственных сценариях (Критерии Т1, Т2, О4)

Все сценарии выполняются со 100% доставкой миссий, без столкновений и наездов на пешеходов.

| Сценарий | Условия испытания | Результат | Подтверждение в коде и логах |
| :--- | :--- | :---: | :--- |
| **01_clear** | Чистая видимость, штатная логистика | **100.0** | Доставка всех миссий, соблюдение скоростных зон |
| **02_gnss_shadow** | **143 м без ГНСС**, узкие коридоры | **100.0** | Scan-match Левенберга-Марквардта по стенам |
| **03_fog_snow** | Туман (лидар 6 м), снежные шумы | **98.41 - 98.76** | Статистический фильтр осадков и адаптивный скоростной коридор |
| **04_busy_yard** | 6 пешеходов, интенсивный трафик | **98.71 - 98.87** | Трекинг Калмана, превентивное замедление до 0.22 м/с |
| **s1_pallet_2m** | Поддон в 2 м от осевой линии (y=153 при оси y=151) | **99.22** | Латеральный сдвиг траектории: `t=115.3`, `note: offset dy=-0.2` |
| **s2_container_block** | Полное перекрытие проезда контейнером | **100.0** | Локальный перепланировщик A*: `t=147.0`, `note: replan` |
| **s3_wall_removed** | Снос стены склада (расхождение карты) | **100.0** | Детектор `map_missing`: `t=9.8`, стена исключена из матчинга |
| **s4_shadow_start_charger** | Старт в тени ГНСС, финиш на зарядке | **100.0** | Прецизионный dock-snap: `t=42.0`, `status: arrived` |
| **s4b_shadow_lane_lost** | Глубокий снос позы без спутников (seed 1) | **100.0** | Честный переход в `lost`, нулевая скорость: `seed 1`, `t=27.2..27.9` |

### Запуск симуляции одного сценария:
```bash
PYTHONPATH=amrsim-participants uv run python -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json --log out/01.jsonl
```
На Windows (PowerShell):
```powershell
$env:PYTHONPATH="amrsim-participants"; uv run python -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json --log out/01.jsonl
```

### Пакетный прогон по набору сидов:
```bash
uv run python scripts/eval.py --controller team_dreamteam_4_0/controller.py --seeds 1,2,3,7,11,21,42
```

---

## 3. Честность оценки позы и алгоритмы (Критерии Т4, Т5, О1)

Архитектура контроллера разбита на изолированные модули в [`team_dreamteam_4_0/`](team_dreamteam_4_0/):
- локализация ([`localize/`](team_dreamteam_4_0/localize/)): покадровое сопоставление сканов со стенами методом Левенберга-Марквардта с функцией потерь Хубера, стробирование ГНСС 1.5 м ($k \le 0.15$), докование `dock-snap` и защитный поиск позы Coarse-to-Fine при статусе `lost`;
- восприятие ([`perceive/`](team_dreamteam_4_0/perceive/)): евклидова кластеризация точек лидара, фильтрация атмосферных помех, сопровождение объектов одиночным фильтром Калмана и детекторы расхождения карты `map_missing`/`map_extra`;
- планирование и траектория ([`route/`](team_dreamteam_4_0/route/)): чистое преследование Pure Pursuit с кривизно-оптимальным ограничением скорости ($a_{lat} \le 0.85$ м/с²), латеральный сдвиг траектории и локальный A* по сетке при блокировке коридора;
- безопасность ([`safety/`](team_dreamteam_4_0/safety/)): супервизор зазоров со ступенчатыми порогами скорости, геометрический коридор торможения по сырому лидару и аварийный останов estop при критическом сближении.

Инженерное обоснование выбора методов, математический аппарат и анализ альтернатив приведены в документах [`APPROACH.md`](APPROACH.md) и [`results/ALTERNATIVES.md`](results/ALTERNATIVES.md).

---

## 4. Автоматические тесты (Критерий Т5)

Проверка алгоритмических инвариантов, скан-матчера, геометрии, бэкенда и интерфейса оператора (модульные тесты pytest и тесты Vitest фронтенда, 100% green):
```bash
# Тесты алгоритмов и бэкенда:
uv run pytest -v

# Тесты интерфейса АРМ:
npm --prefix arm/frontend test -- --run

# Статический анализ кода:
uv run ruff check
```

---

## 5. Автоматизированное рабочее место оператора (критерий О3)

Веб-станция оператора предоставляет полный инструментарий мониторинга и анализа инцидентов по регламенту критерия О3:
- интерактивный плеер тиков Replay: визуализация 2D-карты предприятия на HTML5 Canvas, истинное положение платформы, оценка позы `pose_est`, пешеходы, сырой лидарный скан, отрисовка препятствий, паллет и контейнеров со шлейфом пути;
- синхронизация сценариев: сквозная синхронизация выбранного сценария между всеми разделами, хранилищем `localStorage` и хэшем URL;
- журнал инцидентов Episodes: фильтрация штрафных эпизодов, переход к проблемному такту по клику, экспорт отчета в CSV;
- журнал рейсов Missions: контроль статусов миссий, времени прибытия и точности докования;
- аналитика и скоринг Analytics: радарная диаграмма по 6 критериям регламента, формулы KaTeX и аудит вычислительного бюджета;
- запуск симуляций Runner: старт прогона сценария из веб-интерфейса через серверный runner с отображением результатов и терминальным выводом логов.

### Локальный запуск АРМ (1 команда):
```bash
python arm/server.py --port 8000
```
Открыть в браузере: `http://localhost:8000` (Swagger UI документация: `http://localhost:8000/docs`).

Сервер спроектирован по модульной архитектуре (`arm/core`, `arm/services`, `arm/transport`, фасад `arm/server.py`) строго на стандартной библиотеке Python без сторонних зависимостей и сразу раздает предсобранный клиентский SPA. Подробная инструкция к АРМ - в [`arm/README.md`](arm/README.md).

### Опциональный запуск в Docker:
```bash
docker compose up --build
```
Интерфейс доступен по адресу: `http://localhost:8000`.

---

## 6. Материалы для защиты:

- презентация решения: [`presentation.pdf`](presentation.pdf);
- инженерное описание подхода: [`APPROACH.md`](APPROACH.md);
- анализ альтернатив и сравнительные замеры: [`results/ALTERNATIVES.md`](results/ALTERNATIVES.md).
