# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Wildberries warranty Telegram bot. Python 3.12, aiogram 3.x, async SQLAlchemy + PostgreSQL, Redis FSM, Alembic, APScheduler, ReportLab PDFs.

## Commands (local, no Docker)

- Always run inside the virtualenv first — outside it imports fail (`ModuleNotFoundError: aiogram`):
  `source .venv/bin/activate`
- Migrations use module form: `python -m alembic upgrade head` (not bare `alembic`)
- Start bot: `python -m app.bot.main`
- Docker: `docker-compose up --build`, then `docker-compose exec bot alembic upgrade head`

## Required services

PostgreSQL and Redis must both be running and reachable (`DATABASE_URL`, `REDIS_URL`) or the bot fails on startup — FSM lives in Redis (`RedisStorage` in `app/bot/main.py`).

## Gotchas

- App runtime uses the **async** driver (`asyncpg`), but Alembic is forced to the **sync** driver (`psycopg2`) via a URL rewrite in `migrations/env.py`. Migration auth/URL failures usually mean `.env` isn't loaded for one of the two paths.
- `WB_STORES_JSON` in `.env` must be valid JSON on a **single line**.
- Keep `.env` strictly `KEY=VALUE` per line; broken lines cause `python-dotenv` failures.
- WB API endpoint mapping is a stub in `app/services/wb_service.py` — wire real endpoints there.

## Entrypoints

- Bot: `app/bot/main.py` · User flow + FSM: `app/handlers/user.py` · Admin moderation: `app/handlers/admin.py` · Scheduler jobs (timeouts + WB sync): `app/services/scheduler_service.py`

## Behavior invariants encoded in code

- Single topic per client across warranty + support flows (`support_topics` mapping + moderation topic reuse).
- Form timeout reminders/expiration apply only to `FORM_*` session states; support chat must not receive form reminders.

See @AGENTS.md for the full operator-focused workflow notes.
