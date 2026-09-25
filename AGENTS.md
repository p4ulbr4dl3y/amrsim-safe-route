# Repository Guidelines

Repository contains the AMR (Autonomous Mobile Robot) platform controller and operator station (АРМ) for the "Safe Route" challenge (`amr-sim 0.2`, schema `amr-1.0`).

- **Backend**: Python >=3.10 controller in `backend/` (`controller.py`, `geom.py`, `localize.py`, `perceive.py`, `route.py`, `safety.py`, `scenarios/`).
- **Frontend**: Vite + React 19 + TypeScript + Tailwind CSS SPA operator workstation in `frontend/` (Canvas 2D map, telemetry replay, episode inspector).
- **SDUI Server**: Python stdlib HTTP Server-Driven UI in `scripts/server.py` serving `/api/ui/*`, `/api/run`, and telemetry.
- **Engine**: Baseline simulator engine in `amrsim-participants/` (read-only).

---

## Agent Operating Protocol

1. **Caveman Mode (`/caveman`)**:
   - ALL agents and subagents MUST use caveman communication mode.
   - Ultra-compressed responses, minimal filler, no pleasantries, pure technical facts and results.

2. **Delegation to Subagents**:
   - The primary agent MUST delegate coding, execution, long-running tasks, and heavy research to subagents (`invoke_subagent`).
   - The primary agent MUST remain free and responsive to user questions and guidance at any time, never blocking the main chat on code execution.

3. **Mandatory Testing & Test Writing**:
   - When adding or changing any functionality, agents MUST write corresponding unit tests in `tests/` covering the new logic.
   - After completing any task, agents MUST run and verify the test suite.

4. **Zero-Failure Invariant**:
   - The system must ALWAYS remain green and fault-tolerant.
   - All tests (`pytest tests/`) must pass 100%.
   - Controller isolation check (`amrsim check backend`) must have 0 violations and 0 warnings.
   - Frontend build (`npm run build`) must compile with 0 errors.

---

## Build & Test Commands

- **Run Python Tests**:
  `pytest tests/`
- **Run Single Focused Test**:
  `pytest tests/test_geom.py -k test_point_to_segment`
- **Controller Sandbox & Isolation Check**:
  `python -m amrsim check backend/controller.py` or `python -m amrsim check backend` (requires `PYTHONPATH=amrsim-participants` if amrsim not installed in site-packages)
- **Run Single Simulator Scenario**:
  `python -m amrsim run amrsim-participants/scenarios/01_clear.json --controller backend/controller.py --seed 7 --report out/01_clear.json --log out/01_clear.jsonl`
- **Run Full Evaluation Benchmark**:
  `python scripts/eval.py --controller backend/controller.py --seed 7`
- **Run SDUI Backend Server**:
  `python scripts/server.py --port 8000`
- **Frontend Build & Dev**:
  `cd frontend && npm install && npm run build` (dev server: `npm run dev`)

---

## Architecture & Code Boundaries

- `backend/`: Production controller package. Entry point `backend/controller.py` (`step(obs) -> (v, w, st, pe, note)`).
  - `geom.py`: 2D vector, segment projection, AABB, raycast math.
  - `localize.py`: EKF with IMU/odometry integration, Gauss-Newton wall scan-matching, GNSS Mahalanobis gating, dock-snap.
  - `perceive.py`: Lidar clustering, snow/fog false echo rejection, pedestrian tracking.
  - `route.py`: Pure pursuit trajectory tracker, lateral lane shift, local A* bypass.
  - `safety.py`: Clearance calculation (`hum`/`obj`), speed governor, emergency stop (`estop`), diagnostic notes.
  - `scenarios/`: Team edge-case validation scenarios (s1–s5).
- `frontend/`: Standalone operator workstation SPA (hash routing `#/dashboard`, `#/replay`, `#/episodes`, `#/missions`, `#/analytics`, `#/runner`). Connected via Server-Driven UI API (`frontend/src/api/client.ts`) with static fallback.
- `scripts/server.py`: SDUI backend API handling scenario telemetry streaming, report metrics, and live simulation execution.

---

## Critical Gotchas & Constraints

- **Zero-Violation Sandbox Rule**: `backend/controller.py` and its imported modules MUST ONLY use `numpy` and the Python standard library. Never import `amrsim`, `scipy`, `threading`, `multiprocessing`, `ctypes`, or `inspect`. Any external import triggers `VIOLATION` in `amrsim check` resulting in 0 points.
- **Root Cleanliness**: Root `requirements.txt` must only declare `numpy`. All frontend dependencies must remain strictly inside `frontend/package.json`.
- **Do Not Commit**: `frontend/node_modules/`, `frontend/dist/`, `page design/`, and test artifacts in `out/`.
- **Conventional Commits**: `type(scope): concise description`. PRs targeting frontend should only touch `frontend/` and `.gitignore`.
