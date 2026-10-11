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

Multi-server mode
- Leave `DISCORD_GUILD_ID` unset to enable global command sync
- The bot will create the `LumaBot` category and required channels in every server it joins
- Every server has its own data. A member is one row per (Discord user, server), so XP, streaks,
  badges, tickets, standups, phases, sprints and journals in one server are invisible in another.
  Members run `/member register` (and `/member github`) once per server
- Shared across servers: badge definitions, XP values, and the built-in learning tracks
- A new server starts with no phases; a Lead or Professor adds them with `/phase create`

Webhook setup
- Expose only the webhooks service publicly
- Point GitHub webhooks to: `https://<your-domain>/webhooks/github` (port 8100)
- Use `GITHUB_WEBHOOK_SECRET` to validate signatures
- One webhook URL serves every server. An event is delivered to the server(s) whose project is
  linked to that repository with `/project link-repo`; events from unlinked repositories are ignored

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
# via supabase CLI or directly in SQL Editor, in numeric order
psql $SUPABASE_URL -f app/migrations/001_bot_tables.sql
psql $SUPABASE_URL -f app/migrations/002_seed.sql
# ... 004 through 015
```

`015_multi_guild.sql` splits data per server. Before running it, set `home_guild` at the top of
the file to the Discord server ID that owns the existing data, stop the bot, apply it, then deploy.
