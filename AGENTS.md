# Repository Guidelines

## Project Structure & Module Organization
- `server/` Flask API and core logic; see `server/api/` for routes, `server/core/` for services, and `server/utils/` for helpers.
- `webui/` Vue 3 + TypeScript frontend; `webui/src/views/` are pages, `webui/src/components/` are shared UI, `webui/src/stores/` holds Pinia stores.
- `batch/`, `updater/`, and `proxy/` are Go services; built binaries live at `batch/batch`, `updater/updater`, and `proxy/pt-nexus-box-proxy`.
- `server/configs/` contains site YAML mappings; `server/data/` holds runtime data; `wiki/` stores documentation.

## Build, Test, and Development Commands
Frontend (Node 20+/pnpm):
```bash
cd webui
pnpm install
pnpm dev        # local UI on 5173
pnpm build      # outputs webui/dist
```
Backend (Python 3.12):
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r server/requirements.txt
python server/app.py
```
Go services (see each `go.mod` for versions):
```bash
./batch/build.sh
./updater/build.sh
./proxy/build.sh
```
Full stack: `./start-services.sh` (expects built binaries).

## Coding Style & Naming Conventions
- Python: 4-space indentation, snake_case modules and functions; keep imports grouped.
- Vue/TS: 2-space indentation; components in `PascalCase.vue`, views end with `*View.vue`.
- Go: standard `gofmt` formatting.
- Lint/format: `pnpm lint` (oxlint + eslint) and `pnpm format` (prettier).

## Testing Guidelines
- Backend smoke test: `cd server && python test_functionality.py`.
- Frontend checks: `pnpm type-check` and `pnpm lint`.
- No formal unit test suite is wired in; add targeted tests when changing parsing or upload logic.

## Configuration & Data
- Local configuration uses `server/.env` and `server/data/config.json`; set `DB_TYPE` to `sqlite`, `mysql`, or `postgresql`.
- Treat `server/data/` as runtime state; avoid committing local DB or cache changes unless updating fixtures intentionally.

## Commit & Pull Request Guidelines
- Git history uses minimal numeric messages (for example, `7`); no enforced convention. Prefer short, descriptive summaries.
- If you change `webui/`, `batch/`, `updater/`, or `proxy/`, commit rebuilt outputs (`webui/dist/`, `batch/batch`, `updater/updater`, `proxy/pt-nexus-box-proxy`). The `pre-commit` hook can automate this.
- If `CHANGELOG.json` changes, run `python sync_changelog.py` to update `readme.md` and `wiki/docs/index.md`.
- PRs should explain scope, config impacts, and include UI screenshots when applicable.
