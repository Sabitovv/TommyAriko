# Wildberries Warranty Bot

Production-oriented Telegram bot for warranty activation with moderation flow, support topics, and PDF warranty cards.

## Stack

- Python 3.12
- aiogram 3.x
- PostgreSQL + SQLAlchemy async
- Redis FSM storage
- Alembic
- APScheduler
- ReportLab PDF
- Docker / docker-compose

## Quick start

1. Copy env file:

```bash
cp .env.example .env
```

2. Configure `.env` (bot token, admin group, WB tokens).
   - `WB_STORES_JSON` must be valid JSON on one line.
   - For local run use:
     - `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/warranty`
     - `REDIS_URL=redis://127.0.0.1:6379/0`
     - `PDF_OUTPUT_DIR=./storage/pdfs`
     - `MEDIA_OUTPUT_DIR=./storage/media`
3. Start infrastructure and bot:

```bash
docker-compose up --build
```

4. Run migrations in bot container:

```bash
docker-compose exec bot alembic upgrade head
```

## Project structure

```
app/
  bot/
  handlers/
  services/
  repositories/
  models/
  middlewares/
  filters/
  utils/
  keyboards/
  states/
  admin/
migrations/
```

## Local run (no Docker)

1. Create/activate virtualenv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Ensure PostgreSQL and Redis are running locally.
3. Apply migrations:

```bash
python -m alembic upgrade head
```

4. Start bot:

```bash
python -m app.bot.main
```

## Core flows

- `/start` -> activation warning + start/support buttons
- FSM: full name -> city -> phone -> product (button only) -> article validation -> screenshot -> confirmation
- Application status: `PENDING / APPROVED / REJECTED / NEEDS_CORRECTION`
- Moderation in Telegram forum topics
- Support bridge: user question -> admin topic, admin reply -> user DM
- Session timeout: reminder at 30 minutes, reset at 60 minutes

## Notes

- Add real WB API endpoint mapping in `app/services/wb_service.py`.
- Add admin ACL filter if you need strict admin-only moderation actions.
- Set persistent storage volumes for `storage/` in production.
- See `AGENTS.md` for operator-focused gotchas and workflow constraints.
# TommyAriko
