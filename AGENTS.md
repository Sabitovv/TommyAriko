# AGENTS.md

## Quick start (local)
- Always run inside the repo virtualenv, otherwise imports fail (`ModuleNotFoundError: aiogram`, etc.):
  - `source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Run migrations with module form: `python -m alembic upgrade head`
- Start bot: `python -m app.bot.main`

## Required services
- PostgreSQL must be running and reachable from `DATABASE_URL`.
- Redis must be running and reachable from `REDIS_URL`.
- FSM uses Redis (`RedisStorage` in `app/bot/main.py`), bot will fail without it.

## Environment gotchas
- `WB_STORES_JSON` must be valid JSON on a **single line** in `.env`.
  - Example: `WB_STORES_JSON=[{"store_id":"store_1","token":"..."},{"store_id":"store_2","token":"..."}]`
- Keep `.env` strictly `KEY=VALUE` per line. Broken lines cause `python-dotenv` parse warnings and runtime failures.
- For local runs, prefer:
  - `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/warranty`
  - `REDIS_URL=redis://127.0.0.1:6379/0`
  - `PDF_OUTPUT_DIR=./storage/pdfs`
  - `MEDIA_OUTPUT_DIR=./storage/media`

## Migrations detail
- App runtime uses `asyncpg`, but Alembic is forced to sync driver in `migrations/env.py` (`psycopg2`) via URL rewrite.
- If migrations fail with auth/URL issues, verify `.env` is loaded and connection works for both app and Alembic.

## Runtime architecture entrypoints
- Bot entrypoint: `app/bot/main.py`
- User flow + FSM: `app/handlers/user.py`
- Admin moderation callbacks: `app/handlers/admin.py`
- Scheduler jobs (timeouts + WB sync): `app/services/scheduler_service.py`
- WB catalog sync and dedup: `app/services/wb_service.py`

## Behavior assumptions encoded in code
- Single topic per client is enforced across warranty/support flows via `support_topics` mapping and moderation topic reuse.
- Form timeout reminders/expiration apply only to `FORM_*` session states; support chat should not receive form reminders.

## Docker
- Compose file starts `db`, `redis`, and `bot` only (`docker-compose.yml`).
- After `docker-compose up --build`, apply migrations in container: `docker-compose exec bot alembic upgrade head`.
