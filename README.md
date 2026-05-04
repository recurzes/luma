# Luma

Discord bot for the Lab Manual Architect dev team.

**Stack:** Python 3.12 · discord.py · Supabase (Postgres) · SQLModel · FastAPI · APScheduler · Docker

## Quick Start

```bash
cp .env.example .env
# fill in .env values

pip install .
python app/bot.py
```

## Docker

```bash
docker-compose up --build
```

Services:
- `lumabot` — Discord bot (port N/A, outbound only)
- `lumabot-webhooks` — FastAPI webhook bridge (port 8100)

## Structure

```
app/
├── bot.py          # entry point
├── config.py       # Pydantic settings (fail-fast on missing vars)
├── database.py     # Supabase client singleton
├── cogs/           # discord.py Cog modules
├── services/       # business logic (no Discord dependency)
├── models/         # SQLModel table definitions
├── webhooks/       # FastAPI app for GitHub webhooks
├── scheduler/      # APScheduler job definitions
├── embeds/         # Discord embed builders
├── tests/          # pytest
└── migrations/     # SQL migration files
```

## Database

Apply migrations to Supabase in order:

```bash
# via supabase CLI or directly in SQL Editor
psql $SUPABASE_URL -f devbot/migrations/001_bot_tables.sql
psql $SUPABASE_URL -f devbot/migrations/002_seed.sql
```
