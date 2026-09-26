"""HTTP request handler and transport routing for AMR SafeRoute SDUI server."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from arm.core import config, runner
from arm.services import storage, view_models
from arm.transport.docs import OPENAPI_SPEC, SWAGGER_UI_HTML

ROOT_DIR: Path = config.ROOT_DIR
FRONTEND_DIST: Path = config.FRONTEND_DIST
SCENARIOS_DIR: Path = config.SCENARIOS_DIR
TEAM_SCENARIOS_DIR: Path = config.TEAM_SCENARIOS_DIR
SCENARIO_META: dict[str, dict[str, str]] = config.SCENARIO_META

build_dashboard_view_model = view_models.build_dashboard_view_model
build_replay_view_model = view_models.build_replay_view_model
build_episodes_view_model = view_models.build_episodes_view_model
build_missions_view_model = view_models.build_missions_view_model
build_analytics_view_model = view_models.build_analytics_view_model
run_simulation = runner.run_simulation
get_scenario_report = storage.get_scenario_report
parse_ticks_log = storage.parse_ticks_log


def generate_episodes_csv(scenario_id: str) -> bytes:
    norm_id = config.normalize_scenario_id(scenario_id)
    ep_vm = build_episodes_view_model(norm_id)
    episodes = ep_vm.get("episodes", [])

    lines = [
        "Episode ID,Type,Category,Severity,Start (s),End (s),X,Y,Speed (m/s),Hum Dist (m),Obj Dist (m),PE Error (m),Cost (pts),Explanation"
    ]
    for ep in episodes:
        tk_snap = ep.get("telemetrySnapshot") or {}
        v_raw = tk_snap.get("v")
        v_val = (
            f"{float(v_raw):.2f}"
            if v_raw is not None and isinstance(v_raw, (int, float))
            else ""
        )
        hum_raw = tk_snap.get("hum")
        hum_val = (
            f"{float(hum_raw):.2f}"
            if hum_raw is not None and isinstance(hum_raw, (int, float))
            else ""
        )
        obj_raw = tk_snap.get("obj")
        obj_val = (
            f"{float(obj_raw):.2f}"
            if obj_raw is not None and isinstance(obj_raw, (int, float))
            else ""
        )
        pe_raw = tk_snap.get("pe_error")
        pe_val = (
            f"{float(pe_raw):.4f}"
            if pe_raw is not None and isinstance(pe_raw, (int, float))
            else ""
        )
        cost_val = f"{config._safe_float(ep.get('cost'), 0.0):.2f}"
        expl = str(ep.get("ruleExplanation", "")).replace('"', '""')

        lines.append(
            f"{ep.get('id')},{ep.get('type')},{ep.get('category')},{ep.get('severity', 'info')},"
            f"{ep.get('t_start')},{ep.get('t_end')},{ep.get('x')},{ep.get('y')},"
            f'{v_val},{hum_val},{obj_val},{pe_val},{cost_val},"{expl}"'
        )

    return ("\ufeff" + "\n".join(lines)).encode("utf-8")


class AMRServerHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # Полная поддержка CORS
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"
        )
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def send_json(self, data: dict[str, Any] | list[Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ----------------------------------------------------------------------
        # 0. API: OpenAPI спецификация и Swagger UI документация
        # ----------------------------------------------------------------------
        if path == "/api/openapi.json":
            return self.send_json(OPENAPI_SPEC)

        if path.rstrip("/") in ("/docs", "/api/docs", "/amr/docs", "/amr/api/docs") or path in ("/docs/", "/api/docs/"):
            content = SWAGGER_UI_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ----------------------------------------------------------------------
        # 1. API: список сценариев
        # ----------------------------------------------------------------------
        if path == "/api/scenarios":
            try:
                scenarios = []
                seen = set()

                # Стандартные сценарии
                if SCENARIOS_DIR.exists():
                    for f in sorted(SCENARIOS_DIR.glob("*.json")):
                        sc_id = f.stem
                        if sc_id not in seen:
                            seen.add(sc_id)
                            meta = SCENARIO_META.get(sc_id, {})
                            rep = get_scenario_report(sc_id)
                            rep_score = rep.get("score") if isinstance(rep, dict) else None
                            score = rep_score.get("total") if isinstance(rep_score, dict) else None
                            scenarios.append(
                                {
                                    "id": sc_id,
                                    "name": meta.get("title", f"{sc_id}.json"),
                                    "description": meta.get(
                                        "description", "Сценарий тестирования AMR SafeRoute"
                                    ),
                                    "type": "standard",
                                    "file": str(f.relative_to(ROOT_DIR)).replace("\\", "/"),
                                    "hasReport": isinstance(rep, dict),
                                    "score": score,
                                }
                            )

                # Пользовательские сценарии команды
                if TEAM_SCENARIOS_DIR.exists():
                    for f in sorted(TEAM_SCENARIOS_DIR.glob("*.json")):
                        sc_id = f.stem
                        if sc_id not in seen:
                            seen.add(sc_id)
                            meta = SCENARIO_META.get(sc_id, {})
                            rep = get_scenario_report(sc_id)
                            rep_score = rep.get("score") if isinstance(rep, dict) else None
                            score = rep_score.get("total") if isinstance(rep_score, dict) else None
                            scenarios.append(
                                {
                                    "id": sc_id,
                                    "name": meta.get("title", f"backend/{sc_id}.json"),
                                    "description": meta.get(
                                        "description", "Собственный сценарий команды О4"
                                    ),
                                    "type": "custom",
                                    "file": str(f.relative_to(ROOT_DIR)).replace("\\", "/"),
                                    "hasReport": isinstance(rep, dict),
                                    "score": score,
                                }
                            )

                return self.send_json(scenarios)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 2. SDUI: модель представления дашборда
        # ----------------------------------------------------------------------
        if path == "/api/ui/dashboard":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_dashboard_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 3. SDUI: модель представления плеера
        # ----------------------------------------------------------------------
        if path == "/api/ui/replay":
            try:
                sc_id = params.get("scenario", ["04_busy_yard"])[0]
                seed_raw = params.get("seed", [7])[0]
                try:
                    seed = int(seed_raw)
                except (ValueError, TypeError):
                    seed = 7
                vm = build_replay_view_model(sc_id, seed)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 4. SDUI: модель представления эпизодов
        # ----------------------------------------------------------------------
        if path == "/api/ui/episodes":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_episodes_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 5. SDUI: модель представления миссий
        # ----------------------------------------------------------------------
        if path == "/api/ui/missions":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_missions_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 6. SDUI: модель представления аналитики
        # ----------------------------------------------------------------------
        if path == "/api/ui/analytics":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                vm = build_analytics_view_model(sc_id)
                return self.send_json(vm)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 7. Обратная совместимость: /api/report и /api/ticks
        # ----------------------------------------------------------------------
        if path == "/api/report":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            rep = get_scenario_report(sc_id)
            if rep:
                return self.send_json(rep)
            return self.send_json({"error": "Report not found"}, status=404)

        if path == "/api/ticks":
            sc_id = params.get("scenario", ["04_busy_yard"])[0]
            try:
                res = parse_ticks_log(sc_id)
                return self.send_json(res)
            except FileNotFoundError:
                return self.send_json({"error": "Ticks log not found"}, status=404)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 8. API: экспорт в CSV
        # ----------------------------------------------------------------------
        if path == "/api/export/csv":
            try:
                raw_id = params.get("scenario", ["04_busy_yard"])[0]
                sc_id = config.normalize_scenario_id(raw_id)
                csv_text = generate_episodes_csv(sc_id)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="episodes_{sc_id}.csv"'
                )
                self.send_header("Content-Length", str(len(csv_text)))
                self.end_headers()
                self.wfile.write(csv_text)
                return
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # 9. Статические файлы фронтенда
        # ----------------------------------------------------------------------
        if FRONTEND_DIST.exists():
            # Раздача файла, если путь существует в dist
            file_path = FRONTEND_DIST / path.lstrip("/")
            if file_path.is_file():
                return super().do_GET()
            # Для маршрутов SPA отдается index.html
            index_file = FRONTEND_DIST / "index.html"
            if index_file.exists():
                with open(index_file, "rb") as f:
                    content = f.read()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_json({"error": "Endpoint not found", "path": path}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # ----------------------------------------------------------------------
        # API: сохранение сценария
        # ----------------------------------------------------------------------
        if path in ("/api/scenarios/save", "/api/scenario/save", "/api/scenarios"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return self.send_json(
                    {"error": "Bad Request: invalid JSON payload"}, status=400
                )

            if not isinstance(payload, dict):
                return self.send_json(
                    {"error": "Bad Request: payload must be a JSON object"}, status=400
                )

            sc_id = payload.get("id") or payload.get("name")
            sc_data = payload.get("scenario") or payload.get("data") or payload
            try:
                safe_id, target_file = storage.save_scenario(sc_data, scenario_id=sc_id)
                rel_file = str(target_file.relative_to(config.ROOT_DIR)).replace("\\", "/")
                return self.send_json(
                    {
                        "ok": True,
                        "success": True,
                        "id": safe_id,
                        "file": rel_file,
                        "message": f"Сценарий успешно сохранен в {rel_file}",
                    },
                    status=201,
                )
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        # ----------------------------------------------------------------------
        # API: запуск симуляции
        # ----------------------------------------------------------------------
        if path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                payload = {}

            try:
                if not isinstance(payload, dict):
                    return self.send_json(
                        {"error": "Bad Request: payload must be a JSON object"}, status=400
                    )

                scenario = payload.get("scenario", "04_busy_yard")
                if not isinstance(scenario, str) or not scenario.strip():
                    return self.send_json(
                        {"error": "Bad Request: scenario must be a non-empty string"}, status=400
                    )

                scenario_data = payload.get("scenarioData") or payload.get("scenario_data")

                controller = payload.get("controller", "backend/controller.py")
                if not isinstance(controller, str) or not (
                    controller.startswith("team/")
                    or controller.startswith("backend/")
                    or controller.startswith("team_dreamteam_4_0/")
                ):
                    return self.send_json(
                        {"error": "Bad Request: invalid controller path"}, status=400
                    )

                if controller == "team/controller.py" or controller.startswith("team/"):
                    controller = (
                        "backend/" + controller[len("team/") :]
                        if controller.startswith("team/")
                        else "backend/controller.py"
                    )

                raw_seed = payload.get("seed", 7)
                try:
                    seed = int(raw_seed)
                except (ValueError, TypeError):
                    return self.send_json(
                        {"error": "Bad Request: seed must be an integer"}, status=400
                    )

                cheat = bool(payload.get("cheatPose", False))
            except Exception as e:
                return self.send_json({"error": f"Bad Request: {e}"}, status=400)

            try:
                import inspect

                sig = inspect.signature(run_simulation)
                if "scenario_data" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                ):
                    res = run_simulation(
                        scenario_id=scenario,
                        controller_path=controller,
                        seed=seed,
                        cheat=cheat,
                        scenario_data=scenario_data,
                    )
                else:
                    res = run_simulation(
                        scenario_id=scenario,
                        controller_path=controller,
                        seed=seed,
                        cheat=cheat,
                    )
                # Формирование массива логов для терминала страницы запуска
                res["logs"] = runner.format_simulation_logs(scenario, controller, seed, res)
                return self.send_json(res)
            except Exception as e:
                return self.send_json({"error": str(e)}, status=500)

        self.send_json({"error": "POST endpoint not found", "path": path}, status=404)
