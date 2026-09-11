# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MinerU Tianshu (天枢) — an AI data preprocessing platform that turns PDFs, Office docs, images, audio,
video and bioinformatics files into Markdown + structured JSON. Vue 3 frontend, FastAPI API server,
LitServe GPU worker pool, SQLite task queue, optional Redis queue / MCP server / RustFS object storage.

Code comments, logs and docs are predominantly Simplified Chinese — match that when editing existing files.

## Commands

### Docker (primary deployment path)

```bash
make setup           # first-time: runs setup.sh (interactive deployment wizard)
make build | start | stop | restart | status | logs
make logs-worker     # per-service logs (also logs-backend, logs-frontend)
make shell-worker    # exec into a container
make test-gpu        # verify torch CUDA inside the worker
make validate        # docker compose config
make dev             # docker-compose.dev.yml (hot reload + debugpy)
```

`make` reads `REDIS_QUEUE_ENABLED` from the root `.env` and adds `--profile redis` when true.
`setup.sh` (repo root) is the single deployment entry: `bash setup.sh` (interactive), or
`bash setup.sh --mode <gpu|pipeline|cpu|offline-build|offline-deploy|dev> [--gpus N] [--concurrency N] [--yes] [--dry-run]`.
Offline/air-gapped: `--mode offline-build` on a connected machine (bundle in `docker-images/`), then
`--mode offline-deploy` on the target. Mac CPU local dev: `--mode cpu`.

### Local backend

```bash
cd backend
cp .env.example .env          # REQUIRED — start_all.py exits if backend/.env is missing
python start_all.py                       # API 8000 + worker 8001
python start_all.py --enable-mcp --mcp-port 8002
python start_all.py --workers-per-device 2 --devices 0,1 --accelerator cuda
```

All backend processes must run with `backend/` as CWD (imports are top-level: `from utils import ...`,
`from auth import ...`). Individual services: `python api_server.py`, `python litserve_worker.py`,
`python task_scheduler.py --enable-scheduler`, `python mcp_server.py`.

### Frontend

```bash
cd frontend && npm install
npm run dev      # :3000, proxies /api -> localhost:8000 (vite.config.ts)
npm run build    # tsc && vite build -> dist/
```

### Lint

There is **no test suite**. The quality gate is pre-commit, which is also the only CI job
(`.github/workflows/pylint.yml`):

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files
ruff format backend/ && ruff check --fix backend/
```

Ruff: `select = ["E","F"]`, `ignore = ["E402","E501"]`, line-length 120, target py312, double quotes.
Hooks also run shellcheck, markdownlint, and enforce LF endings (except `.bat/.cmd/.ps1`).

## Architecture

### Process topology

`start_all.py` spawns independent subprocesses; in Docker each is a separate container running the same
`tianshu-backend` image with a role argument via `scripts/docker-entrypoint.sh` (`api` / `worker` / `mcp`):

| Service | Default port | Entry |
|---|---|---|
| API server (FastAPI) | 8000 | `api_server.py` |
| Worker pool (LitServe) | 8001 | `litserve_worker.py` |
| MCP server | 8002 | `mcp_server.py` |
| Scheduler (optional) | — | `task_scheduler.py` |
| Frontend (nginx) | 80 | `frontend/` |

### Pull-based task queue

The API **never calls the worker**. It writes a row to the `tasks` table and returns immediately.
Each worker runs `_worker_loop()`, polling `TaskDB.get_next_task()` every `--poll-interval` (0.5s).

Claiming is atomic: `BEGIN IMMEDIATE` plus `UPDATE ... WHERE task_id=? AND status='pending'`, retried when
`rowcount == 0` (another worker won the race). With `REDIS_QUEUE_ENABLED=true`, `redis_queue.py`
(sorted-set priority queue) is tried first and SQLite is the automatic fallback — SQLite stays the source
of truth for metadata and results either way.

`task_db.py` owns the schema and performs **in-place migrations on startup** by `SELECT`ing a column and
catching `sqlite3.OperationalError` to `ALTER TABLE`. Add new columns with that same pattern, never by
editing `CREATE TABLE` alone — existing deployments would not pick it up.

`auth/auth_db.py` reuses the **same SQLite file** (`DATABASE_PATH`) as the task DB.

### Engine routing (`litserve_worker.py::_process_task`)

Per-task pipeline: vLLM container switch → legacy Office conversion → PDF split → watermark removal →
engine dispatch → normalize → persist.

Dispatch is keyed on the task's `backend` string:

- `sensevoice` → audio engine; `video` → video engine
- anything containing `pipeline` / `vlm-` / `hybrid-` → MinerU (`options["parse_mode"] = backend`)
- `auto` → sniffed by extension: format engines → audio → video → MinerU (PDF/images/DOCX/XLSX/PPTX) → LibreOffice conversion for
  legacy `.doc/.xls/.ppt` → MarkItDown fallback (HTML/TXT/CSV)
- otherwise → looked up in `FormatEngineRegistry`

Every engine is imported behind a try/except with an `X_AVAILABLE` flag, so a missing optional dependency
degrades that one backend instead of killing the worker. Preserve that pattern when adding engines.

`VLLMController.ensure_service()` enforces **mutual exclusion between vLLM containers**
(`tianshu-vllm-mineru`) by stopping the conflicting one to free VRAM — the
worker talks to the Docker socket to do this.

### Output contract

Every engine's raw output directory goes through `output_normalizer.normalize_output(dir, handle_method)`,
which standardizes to `result.md` / `result.json` / `images/`, then uploads images to RustFS (S3-compatible,
`storage/rustfs_client.py`) and rewrites image paths to public URLs.

The worker then writes a JSON blob into the `tasks.data` column with keys the frontend depends on:
`pdf_path` (left-hand PDF preview), `json_content` (right-hand layout/bbox rendering), `markdown`,
`markdown_file`. Renaming these keys breaks `TaskDetail.vue`.

### Parent/child tasks (large PDFs)

PDFs above `PDF_SPLIT_THRESHOLD_PAGES` are split in the **worker** (not the API) into child tasks of
`PDF_SPLIT_CHUNK_SIZE` pages: `convert_to_parent_task` → N × `create_child_task` → each child processed
independently → `on_child_task_completed` returns the parent id once the last child lands →
`_merge_parent_task_results` concatenates Markdown/JSON in page order. Failures route through
`on_child_task_failed`.

### Format engine plugin system

To add a document format: subclass `FormatEngine` (`backend/format_engines/base.py`), set
`SUPPORTED_EXTENSIONS` / `FORMAT_NAME` / `FORMAT_DESCRIPTION`, implement `parse()` returning
`{format, markdown, json_content, metadata, summary}`, then register it in `format_engines/__init__.py`.
It then becomes routable both as an explicit `backend` value and via `auto` detection, and appears in
`GET /api/v1/engines`. FASTA and GenBank are the reference implementations.

### Auth

JWT (access + refresh) or API key, resolved by `auth/dependencies.py::get_current_user`, which tries the
bearer token then the API key. Authorization uses the `require_permission(...)` / `require_role(...)`
dependency factories. Tasks carry `user_id`; non-admin users only see their own. Optional OIDC/SAML SSO
lives in `auth/sso.py` and is registered conditionally.

### API surface

`/api/v1/*` from `api_server.py` (task submit/get/cancel/retry/pause/resume/clear-cache, queue stats,
admin cleanup and reset-stale, `/engines`, `/health`, file serving) plus `auth/routes.py` at
`/api/v1/auth/*`. File-serving endpoints resolve the path then check `is_relative_to(OUTPUT_DIR)` — keep
that guard on any new path-taking endpoint. Interactive docs at `http://localhost:8000/docs`.

## Configuration

Two separate `.env` files; do not conflate them:

- **Root `.env`** (from `.env.example`) — consumed by docker-compose and the Makefile. Ports, `GPU_COUNT`,
  `WORKER_MEMORY_LIMIT`, `JWT_SECRET_KEY`, `DATABASE_PATH`, `RUSTFS_*`, `REDIS_*`, `PDF_SPLIT_*`,
  `VITE_API_BASE_URL`.
- **`backend/.env`** (from `backend/.env.example`) — required by `start_all.py` for local runs.

Note that `.env.example` sets `API_PORT=8080` while the code/CLI default is 8000; check which is in play
before debugging a connection failure. Model weights land in `models/`, runtime data in
`data/{uploads,output,db}`, logs in `logs/{backend,worker,mcp}`.
