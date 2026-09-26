.PHONY: help check test lint sim arm verify

# Автоопределение тулчейна: uv если установлен, иначе python3/pip
UV := $(shell command -v uv 2>/dev/null)

ifdef UV
    RUN := uv run
    PY := uv run python
    PYTEST := uv run pytest
    RUFF := uv run ruff
else
    RUN :=
    PY := python3
    PYTEST := pytest
    RUFF := ruff
endif

help:
	@echo "Команды проверки решения Dreamteam 4.0:"
	@echo "  make verify - полный цикл: изоляция Т3, тесты Т5, линтер"
	@echo "  make check  - проверка изоляции пакета контроллера (критерий Т3)"
	@echo "  make test   - запуск модульных тестов (критерий Т5)"
	@echo "  make lint   - проверка качества кода"
	@echo "  make sim    - запуск симуляции сценария 01_clear (критерий Т1)"
	@echo "  make arm    - запуск локальной веб-станции оператора (критерий О3)"

check:
	PYTHONPATH=amrsim-participants $(PY) -m amrsim check team_dreamteam_4_0

test:
	$(PYTEST) -v

lint:
	$(RUFF) check

sim:
	PYTHONPATH=amrsim-participants $(PY) -m amrsim run scenarios/01_clear.json --controller team_dreamteam_4_0/controller.py --seed 7 --report out/01.json

arm:
	$(PY) arm/server.py --port 8000

verify: check test lint
