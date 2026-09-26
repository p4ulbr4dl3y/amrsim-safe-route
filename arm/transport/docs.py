"""OpenAPI 3.0.0 specification generator and Swagger UI HTML template for AMR SafeRoute."""

from __future__ import annotations

from typing import Any

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {
        "title": "AMR SafeRoute Operator Station API",
        "version": "1.0.0",
        "description": (
            "Программный интерфейс автоматизированного рабочего места оператора (АРМ) "
            "платформы Dreamteam 4.0 кейса «Безопасный маршрут». Обеспечивает передачу данных "
            "по архитектуре Server-Driven UI (SDUI), запуск симуляций amrsim, разбор журналов телеметрии "
            "и экспорт инцидентов по контракту amr-1.0."
        ),
        "contact": {
            "name": "Dreamteam 4.0 Support",
        },
    },
    "paths": {
        "/api/scenarios": {
            "get": {
                "summary": "Список доступных сценариев",
                "description": "Возвращает перечень стандартных сценариев соревнований и сценариев команды с метаданными и баллами.",
                "responses": {
                    "200": {
                        "description": "Успешный возврат списка сценариев",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/ScenarioItem"},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/ui/dashboard": {
            "get": {
                "summary": "Модель представления дашборда (SDUI)",
                "description": "Агрегированные KPI, статус выполнения заданий, целевая функция и штрафы для главного экрана.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Модель представления дашборда",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/ui/replay": {
            "get": {
                "summary": "Модель представления плеера телеметрии (SDUI)",
                "description": "Покадровые тики телеметрии платформы, геометрия площадки, положения препятствий и маркеры инцидентов.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    },
                    {
                        "name": "seed",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 7},
                        "description": "Случайное зерно симулятора",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Модель представления интерактивного плеера",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/ui/episodes": {
            "get": {
                "summary": "Модель представления инцидентов и эпизодов (SDUI)",
                "description": "Журнал нарушений правил безопасности, ошибки оценки позы и нештатные остановки с телеметрическими снимками.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Журнал инцидентов",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/ui/missions": {
            "get": {
                "summary": "Модель представления миссий (SDUI)",
                "description": "Статистика рейсов m1, m2: время удержания платформы, допуски позиционирования и эффективность.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Журнал рейсов доставки",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/ui/analytics": {
            "get": {
                "summary": "Модель представления аналитики (SDUI)",
                "description": "Сводный балл по 6 блокам формулы регламента, радарная диаграмма и аудит вычислительного бюджета.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Аналитическая модель представления",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/api/run": {
            "post": {
                "summary": "Запуск автономной симуляции сценария",
                "description": "Инициирует прогон сценария в симуляторе amrsim и возвращает результаты со сводным баллом.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/SimulationRunParams"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Результат выполнения симуляции",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SimulationRunResult"}
                            }
                        },
                    },
                    "400": {"description": "Некорректные параметры запуска"},
                },
            }
        },
        "/api/export/csv": {
            "get": {
                "summary": "Экспорт журнала эпизодов в формате CSV",
                "description": "Выгружает таблицу зафиксированных эпизодов с физическими метриками для аудита экспертной комиссией.",
                "parameters": [
                    {
                        "name": "scenario",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "04_busy_yard"},
                        "description": "Идентификатор сценария",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "CSV-файл журнала эпизодов",
                        "content": {"text/csv": {"schema": {"type": "string"}}},
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "ScenarioItem": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "example": "01_clear"},
                    "name": {"type": "string", "example": "01_clear.json (Ясная погода)"},
                    "description": {"type": "string"},
                    "type": {"type": "string", "enum": ["standard", "custom"]},
                    "file": {"type": "string"},
                    "hasReport": {"type": "boolean"},
                    "score": {"type": "number", "nullable": True},
                },
                "required": ["id", "name", "type", "file"],
            },
            "SimulationRunParams": {
                "type": "object",
                "properties": {
                    "scenario": {"type": "string", "example": "01_clear"},
                    "controller": {
                        "type": "string",
                        "example": "team_dreamteam_4_0/controller.py",
                    },
                    "seed": {"type": "integer", "default": 7},
                    "cheatPose": {"type": "boolean", "default": False},
                },
                "required": ["scenario"],
            },
            "SimulationRunResult": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "score": {"type": "number"},
                    "time": {"type": "number"},
                    "report": {"type": "object"},
                    "stdout": {"type": "string"},
                },
                "required": ["success"],
            },
            "ControlStepOutput": {
                "type": "object",
                "description": "Схема выходных данных такта управления amr-1.0",
                "properties": {
                    "v": {
                        "type": "number",
                        "description": "Линейная скорость платформы, м/с (диапазон 0.0 - 1.5)",
                    },
                    "w": {
                        "type": "number",
                        "description": "Угловая скорость платформы, рад/с (диапазон -1.0 - 1.0)",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["moving", "holding", "docked", "lost", "estop"],
                        "description": "Статус платформы по регламенту соревнований",
                    },
                    "pose_est": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "Оценка позы [x, y, yaw] в глобальной системе координат",
                    },
                    "note": {
                        "type": "string",
                        "description": "Строка диагностических заметок и телеметрии",
                    },
                },
                "required": ["v", "w", "status", "pose_est", "note"],
            },
        }
    },
}

SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>AMR SafeRoute API // Спецификация OpenAPI</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui.css" />
  <style>
    body { margin: 0; background: #fafafa; font-family: sans-serif; }
    .topbar { display: none; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5.11.0/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {
      window.ui = SwaggerUIBundle({
        url: window.location.pathname.replace(/\\/(docs|api\\/docs)\\/?$/, '') + '/api/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    };
  </script>
</body>
</html>
"""
