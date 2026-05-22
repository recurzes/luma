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

## Dokploy (Docker)

Use a two-service setup that mirrors `docker-compose.yml`, with the scheduler running inside the bot process.

Option A: Import a compose file
- Use `dokploy-compose.yml` (recommended for Dokploy) or `docker-compose.yml`
- If you use `docker-compose.yml`, ensure the external network exists or remove the network stanza

Option B: Create two services manually
- **Service 1 (bot)**
  - Build: `Dockerfile`
  - Command: `python -m app.bot`
  - Ports: none
- **Service 2 (webhooks)**
  - Build: `Dockerfile`
  - Command: `uvicorn app.webhooks.main:app --host 0.0.0.0 --port 8100`
  - Ports: `8100:8100`

Required env vars (from `app/config.py` and `.env.example`):
- `DISCORD_TOKEN`
- `DISCORD_GUILD_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `CHANNEL_TASK_FEED`
- `CHANNEL_STANDUP_LOG`
- `CHANNEL_GITHUB_FEED`
- `CHANNEL_CODE_REVIEW`
- `CHANNEL_PHASE_TRACKER`
- `CHANNEL_HELP`
- `CHANNEL_SHOUTOUTS`
- `CHANNEL_ANNOUNCEMENTS`
- `CHANNEL_TIP_OF_THE_DAY`
- `CHANNEL_RESOURCES`
- `CHANNEL_RETRO`
- `CHANNEL_RANKINGS`
- `DEBUG` (optional)
- `DISCORD_ROLE_LEAD` (optional, default: Lead)
- `DISCORD_ROLE_PROFESSOR` (optional, default: Professor)
- `GITHUB_TOKEN` (optional)

Webhook setup
- Expose only the webhooks service publicly
- Point GitHub webhooks to: `https://<your-domain>/` (port 8100)
- Use `GITHUB_WEBHOOK_SECRET` to validate signatures

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
