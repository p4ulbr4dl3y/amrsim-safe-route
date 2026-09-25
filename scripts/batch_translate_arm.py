"""Batch replace English comments with Russian translations in ARM server and frontend.

Adheres strictly to text-stylist guidelines:
- Regular hyphen '-' instead of em-dash or en-dash.
- No redundant parentheticals.
- Russian list style (colon, semicolon separator, ending dot, hyphen bullet).
- Professional engineering style, no emoji.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Python server.py block replacements
SERVER_PY_REPLACEMENTS = [
    ("# In-memory caches to speed up requests", "# Кэш в оперативной памяти для ускорения запросов"),
    ("# Check direct file path if provided", "# Проверка прямого пути к файлу при наличии"),
    ("# If backend/ was requested, map to team/ if present", "# Перенаправление backend/ в team/ при наличии"),
    ("# Search in standard, team, and backend scenario directories", "# Поиск в каталогах стандартных, командных сценариев и сценариев бэкенда"),
    (
        "# Fallback to sample 01_clear.jsonl or 04_busy_yard.jsonl if specific tick log not yet generated",
        "# Использование образцов 01_clear.jsonl или 04_busy_yard.jsonl, если лог тактов еще не сформирован",
    ),
    ("# Invalidate cache for this scenario", "# Сброс кэша для данного сценария"),
    (
        "# Process all ticks: compute pe_error and ensure lidar rays",
        "# Обработка всех тактов: вычисление ошибки оценки позы pe_error и проверка лучей лидара",
    ),
    ("# Generate sample lidar rays if needed", "# Генерация лучей лидара при необходимости"),
    (
        "# Server-Driven UI (SDUI) View Model Builders",
        "# Построители моделей представления интерфейса SDUI",
    ),
    ("# Calculate average localization error from raw ticks", "# Расчет средней ошибки локализации по сырым тактам"),
    ("# Speed history (40 points across the run)", "# История скорости: 40 точек по всей длительности прогона"),
    ("# Recent events constructed from missions and episodes", "# Недавние события, сформированные из миссий и эпизодов"),
    ("# Add delivered missions as success events", "# Добавление выполненных миссий как успешных событий"),
    ("# Add episodes as warnings/info", "# Добавление штрафных эпизодов как предупреждений или информационных сообщений"),
    ("# Add controller state/info event", "# Добавление события состояния контроллера"),
    ("# Sort recent events by time descending", "# Сортировка недавних событий по убыванию времени"),
    ("# Controller performance metrics", "# Метрики производительности контроллера"),
    ("# Preview and history ticks for mini-map", "# Такты предпросмотра и истории для миникарты"),
    ("# Helper to find closest tick by timestamp", "# Поиск ближайшего такта по временной метке"),
    ("# Telemetry snapshot from closest tick", "# Снимок телеметрии из ближайшего такта"),
    (
        "# If scenario had few or no penalty episodes, extract mission events and telemetry highlights",
        "# При малом числе штрафных эпизодов извлечение событий миссий и ключевых точек телеметрии",
    ),
    (
        "# 1. Mission Milestones (Departure, Delivery/Timeout)",
        "# 1. Контрольные точки миссий: отправление, доставка или таймаут",
    ),
    ("# Departure", "# Отправление"),
    ("# Arrival", "# Прибытие"),
    (
        "# 2. Extract notable events from raw ticks (GNSS shadow, obstacles, pedestrians, map extra, stops)",
        "# 2. Извлечение ключевых событий из тактов: тень GNSS, препятствия, пешеходы, расхождения карты, остановки",
    ),
    ("# Avoid duplicates close in time", "# Исключение близких по времени дубликатов"),
    (
        "# 3. If still fewer than 3 events, sample operational checkpoints along the trajectory",
        "# 3. Если событий менее 3, выборка контрольных точек вдоль траектории",
    ),
    (
        "# If episodes list is still empty (e.g. simulation log not present or no events), add informative start/nominal event",
        "# Если список эпизодов пуст, добавление стартового информационного события",
    ),
    ("# Sort all episodes chronologically", "# Хронологическая сортировка всех эпизодов"),
    ("# Collisions: 0 is perfect", "# Столкновения: 0 - идеальный результат"),
    (
        "# HTTP Server Handler",
        "# Обработчик HTTP-сервера",
    ),
    ("# Full CORS support", "# Полная поддержка CORS"),
    ("# 1. API: Scenarios list", "# 1. API: список сценариев"),
    ("# Open standard scenarios", "# Стандартные сценарии"),
    ("# Team custom scenarios", "# Пользовательские сценарии команды"),
    ("# 2. Server-Driven UI: Dashboard View Model", "# 2. SDUI: модель представления дашборда"),
    ("# 3. Server-Driven UI: Replay View Model", "# 3. SDUI: модель представления плеера"),
    ("# 4. Server-Driven UI: Episodes View Model", "# 4. SDUI: модель представления эпизодов"),
    ("# 5. Server-Driven UI: Missions View Model", "# 5. SDUI: модель представления миссий"),
    ("# 6. Server-Driven UI: Analytics View Model", "# 6. SDUI: модель представления аналитики"),
    ("# 7. Backward compatibility: /api/report & /api/ticks", "# 7. Обратная совместимость: /api/report и /api/ticks"),
    ("# 8. API: Export CSV", "# 8. API: экспорт в CSV"),
    ("# 9. Static Frontend files", "# 9. Статические файлы фронтенда"),
    ("# If path exists in dist, serve it", "# Раздача файла, если путь существует в dist"),
    ("# If it's a SPA route, serve index.html", "# Для маршрутов SPA отдается index.html"),
    ("# API: Run Simulation", "# API: запуск симуляции"),
    ("# Prepare logs array for Runner UI terminal", "# Формирование массива логов для терминала страницы запуска"),
    (
        "# Set working directory for SimpleHTTPRequestHandler static serving",
        "# Установка рабочего каталога для статических файлов SimpleHTTPRequestHandler",
    ),
]

# Frontend TS/TSX replacements: file_path -> list of (old_comment, new_comment)
FRONTEND_REPLACEMENTS = {
    "arm/frontend/src/App.tsx": [
        ("// Parse window.location.hash on mount and on hashchange", "// Разбор window.location.hash при монтировании и изменении хэша"),
        ("// Root / redirects to /dashboard as per frontend.md rule", "// Перенаправление корневого пути / на /dashboard"),
        ("// Parse query string", "// Разбор строки параметров запроса"),
        ("// Programmatic navigation handler", "// Обработчик программной навигации"),
    ],
    "arm/frontend/src/components/Latex.tsx": [
        ("// If explicit math prop was passed, render directly", "// Прямой рендеринг при явной передаче свойства math"),
        ("// Split text by $$...$$ and $...$", "// Разделение текста по блочным $$...$$ и строчным $...$ формулам"),
    ],
    "arm/frontend/src/components/MapCanvas.tsx": [
        ("// Viewport transformation: scale and offset", "// Преобразование области просмотра: масштаб и смещение"),
        ("// Auto-fit bounds for mini-map mode (fit entire warehouse bounds)", "// Автоматическое масштабирование для миникарты по границам склада"),
        ("// Handle follow robot or target coordinates (disabled in mini-map)", "// Следование за роботом или центрирование по координатам (отключено на миникарте)"),
        ("// Render loop", "// Цикл отрисовки"),
        ("// Handle high DPI", "// Поддержка экранов с высокой плотностью пикселей High-DPI"),
        ("// Compute active scale and offset (guaranteed fit for mini-map)", "// Вычисление активного масштаба и смещения"),
        ("// Transform helper: world (X, Y) -> screen (px, py)", "// Преобразование мировых координат (X, Y) в экранные (px, py)"),
        ("// 1. Background Grid", "// 1. Фоновая сетка"),
        ("// 20 meters", "// 20 метров"),
        ("// Warehouse outer bounds perimeter border", "// Внешний периметр склада"),
        ("// 2. Drivable Corridors", "// 2. Проезжие коридоры"),
        ("// 3. Zones (Forbidden, Speed limit)", "// 3. Зоны: запретные и с ограничением скорости"),
        ("// 4. Buildings (Warehouse blocks)", "// 4. Здания: складские блоки"),
        ("// 5. Reference Path (dashed line from warehouse to shop_a)", "// 5. Опорный путь: пунктирная линия"),
        ("// 6. Dock Stations", "// 6. Станции доков"),
        ("// Outer circle (tolerance radius)", "// Внешний круг: радиус допуска"),
        ("// Inner solid dot", "// Внутренняя точка"),
        ("// Dock Label", "// Метка дока"),
        ("// 7. AMR Trajectory History Trail", "// 7. След истории траектории робота"),
        ("// Teal-emerald trail matching mockup", "// Изумрудный след траектории"),
        ("// 8. Active Tick: AMR Platform & Sensors", "// 8. Активный такт: платформа и сенсоры"),
        ("// 0.9m platform radius", "// Радиус платформы 0.9 м"),
        ("// 8a. Lidar Rays", "// 8a. Лучи лидара"),
        ("// 8b. Estimated Pose (Purple circle) & Discrepancy Vector", "// 8b. Оценка позы и вектор невязки"),
        ("// Difference line (red dashed)", "// Линия расхождения (красный пунктир)"),
        ("// Purple hollow marker", "// Фиолетовый маркер оценки"),
        ("// 8c. Pedestrians", "// 8c. Пешеходы"),
        ("// Danger circle (3.0 m radius)", "// Зона опасности: радиус 3.0 м"),
        ("// Pedestrian core marker", "// Маркер пешехода"),
        ("// 8d. True AMR Robot (Green / Emerald glyph with heading arrow)", "// 8d. Истинная поза робота со стрелкой курса"),
        ("// Invert theta because screen Y is flipped", "// Инверсия угла th из-за перевернутой экранной оси Y"),
        ("// Outer body ring", "// Внешнее кольцо корпуса"),
        ("// Directional arrow pointing forward (along heading)", "// Стрелка направления курса"),
        ("// Mouse pan & zoom handlers (disabled in mini-map mode)", "// Обработчики панорамирования и масштабирования мыши"),
    ],
    "arm/frontend/src/pages/AnalyticsPage.tsx": [
        ("// Load scenarios on mount", "// Загрузка сценариев при монтировании"),
        ("// Update scenario from queryParams if changed", "// Обновление сценария из параметров URL при изменении"),
        ("// Load analytics when scenario changes", "// Загрузка аналитики при смене сценария"),
        ("// CSV Export handler", "// Экспорт в формате CSV"),
        ("// JSON Export handler", "// Экспорт в формате JSON"),
        ("// Radar points computation (6-axis hexagon)", "// Расчет точек лепестковой диаграммы (6-осевой шестиугольник)"),
        ("// Compute max count in histogram for scaling", "// Расчет максимального значения гистограммы для масштабирования"),
    ],
    "arm/frontend/src/pages/DashboardPage.tsx": [
        ("// Fetch scenarios on mount", "// Загрузка сценариев при монтировании"),
        ("// Fetch dashboard data when scenario changes", "// Загрузка данных дашборда при смене сценария"),
        ("// Loading fallback placeholder if data not yet loaded", "// Заглушка ожидания загрузки данных"),
        ("// Compute speed curve points dynamically for SVG", "// Расчет точек кривой скорости для SVG"),
    ],
    "arm/frontend/src/pages/EpisodesPage.tsx": [
        ("// Fetch scenarios list", "// Загрузка списка сценариев"),
        ("// Update scenario from queryParams if changed", "// Обновление сценария из параметров URL при изменении"),
        ("// Fetch episodes when scenario changes", "// Загрузка эпизодов при смене сценария"),
        ("// CSV Export handler", "// Экспорт в формате CSV"),
        ("// JSON Export handler", "// Экспорт в формате JSON"),
        ("// Dynamic episode types for filter dropdown", "// Типы эпизодов для фильтрации"),
        ("// Filtering", "// Фильтрация"),
    ],
    "arm/frontend/src/pages/MissionsPage.tsx": [
        ("// Fetch scenarios list", "// Загрузка списка сценариев"),
        ("// Update scenario from queryParams if changed", "// Обновление сценария из параметров URL при изменении"),
        ("// Fetch missions for scenario", "// Загрузка миссий для сценария"),
        ("// If id is provided in queryParams, scroll to that card", "// Прокрутка к карточке при передаче id в параметрах URL"),
    ],
    "arm/frontend/src/pages/ReplayPage.tsx": [
        ("// Layers configuration", "// Конфигурация слоев"),
        ("// Load scenarios on mount", "// Загрузка сценариев при монтировании"),
        ("// Update scenario from queryParams if changed", "// Обновление сценария из параметров URL при изменении"),
        ("// Load replay data for selected scenario", "// Загрузка данных воспроизведения для выбранного сценария"),
        ("// If queryParams has t, find matching tick", "// Поиск такта при передаче t в параметрах URL"),
        ("// Default to beginning or interesting moment", "// Переход к началу или первому событию по умолчанию"),
        ("// Handle incoming query params updates when already loaded", "// Обработка обновления параметров URL при загруженных данных"),
        ("// High-precision animation playback loop", "// Цикл воспроизведения анимации высокой точности"),
        ("// If starting at the end, restart from beginning", "// Перезапуск с начала при достижении конца записи"),
        ("// Determine simulation tick rate (Hz): ticks per simulation second", "// Частота тактов симуляции (Гц): тактов в секунду симуляции"),
        ("// Cap delta time to 0.1s to prevent huge jumps on tab switch/lag spike", "// Ограничение delta time значением 0.1 с для исключения скачков"),
        ("// Format time mm:ss.d", "// Форматирование времени в виде мм:сс.д"),
        ("// Determine note & status", "// Определение примечания и статуса"),
    ],
    "arm/frontend/src/pages/RunnerPage.tsx": [
        ("// Execution state", "// Состояние выполнения"),
        ("// Load scenarios on mount", "// Загрузка сценариев при монтировании"),
        ("// Update scenario from queryParams if changed", "// Обновление сценария из параметров URL при изменении"),
        ("// Simulated progress increment while waiting for response", "// Симуляция прироста прогресса во время ожидания ответа"),
    ],
}


def process_server_py() -> None:
    path = Path("arm/server.py")
    content = path.read_text(encoding="utf-8")
    count = 0
    for old, new in SERVER_PY_REPLACEMENTS:
        if old in content:
            content = content.replace(old, new, 1)
            count += 1
        else:
            print(f"Предупреждение: не найдено в arm/server.py: {old}")

    # Syntax validation
    ast.parse(content, filename=str(path))
    path.write_text(content, encoding="utf-8")
    print(f"arm/server.py: заменено комментариев - {count}.")


def process_frontend() -> None:
    for rel_path, pairs in FRONTEND_REPLACEMENTS.items():
        path = Path(rel_path)
        content = path.read_text(encoding="utf-8")
        count = 0
        for old, new in pairs:
            if old in content:
                content = content.replace(old, new, 1)
                count += 1
            else:
                print(f"Предупреждение: не найдено в {rel_path}: {old}")
        path.write_text(content, encoding="utf-8")
        print(f"{rel_path}: заменено комментариев - {count}.")


def main() -> None:
    process_server_py()
    process_frontend()
    print("Перевод комментариев АРМ успешно применен.")


if __name__ == "__main__":
    main()
