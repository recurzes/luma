from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    # Discord
    DISCORD_TOKEN: str = Field(..., description="Bot token from Discord Developer Portal")
    DISCORD_GUILD_ID: int = Field(..., description="Target guild (server) snowflake ID")

    # Supabase
    SUPABASE_URL: str = Field(..., description="Supabase project URL")
    SUPABASE_SERVICE_ROLE_KEY: str = Field(..., description="Service role key (full DB access)")

    # Github Webhook
    GITHUB_WEBHOOK_SECRET: str = Field(..., description="Secret used to verify GitHub webhook signatures")

    # Channel IDs
    CHANNEL_TASK_FEED: int = Field(..., description="#task-feed — live ticket status updates")
    CHANNEL_STANDUP_LOG: int = Field(..., description="#standup-log — compiled daily standups")
    CHANNEL_GITHUB_FEED: int = Field(..., description="#github-feed — commits, PRs, CI results")
    CHANNEL_CODE_REVIEW: int = Field(..., description="#code-review — PR assignments, tier warnings")
    CHANNEL_PHASE_TRACKER: int = Field(..., description="#phase-tracker — phase progress")
    CHANNEL_HELP: int = Field(..., description="#help — /stuck threads")
    CHANNEL_SHOUTOUTS: int = Field(..., description="#shoutouts — kudos and milestone posts")
    CHANNEL_ANNOUNCEMENTS: int = Field(..., description="#announements — phase completions")
    CHANNEL_TIP_OF_THE_DAY: int = Field(..., description="#tip-of-the-day — daily dev tip")
    CHANNEL_RESOURCES: int = Field(..., description="#resources — /share drops")
    CHANNEL_RETRO: int = Field(..., description="#retro — sprint retrospective prompts")
    CHANNEL_RANKINGS: int = Field(..., description="#rankings — weekly XP leaderboard")

    # Optional
    DEBUG: bool = Field(default=False, description="Enable verbose/pretty logging")

    # Discord role names
    DISCORD_ROLE_LEAD: str = Field(default="Lead", description="Discord role name for the lead developer")
    DISCORD_ROLE_PROFESSOR: str = Field(default="Professor", description="Discord role name for the professor")

settings = Settings()