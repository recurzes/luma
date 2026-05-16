from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


def _default_dev_tips() -> list[str]:
    return [
        "Write tests before you think you need them. You already need them.",
        "Read error messages fully before searching. The answer is usually there.",
        "Small, focused commits are easier to review and easier to revert.",
        "Name variables after what they contain, not how they're used.",
        "If you can't explain what a function does in one sentence, break it up.",
        "Every `TODO` comment is a promise to your future self. Keep them.",
        "Avoid abbreviations in variable names — clarity beats brevity.",
        "Before adding a library, ask: can you write this in 20 lines?",
        "Logs are your friend in production. Add them while you still remember what matters.",
        "Document the WHY, not the WHAT — the code already tells you what.",
        "Zero TypeScript `any` types is a lifestyle, not a preference.",
        "Rubber duck debugging works. Find your duck.",
        "If you haven't committed in an hour, something has gone wrong.",
        "The best PR is a small PR. Split your work early.",
        "A bug is just a feature with bad timing.",
    ]


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

    DEV_TIPS: list[str] = Field(default_factory=_default_dev_tips, description="Daily dev tips rotation")

    # Optional
    DEBUG: bool = Field(default=False, description="Enable verbose/pretty logging")

    # Discord role names
    DISCORD_ROLE_LEAD: str = Field(default="Lead", description="Discord role name for the lead developer")
    DISCORD_ROLE_PROFESSOR: str = Field(default="Professor", description="Discord role name for the professor")

    # GitHub
    GITHUB_TOKEN: str = Field(default="", description="GitHub personal access token for API calls")

    T3_PROTECTED_PATHS: list[str] = Field(
        default=[
            "frontend/src/store/",
            "backend/app/schemas/blocks.py",
            "frontend/src/types/blocks.ts",
        ],
        description="File path prefixes that trigger the T3 file guard warning",
    )

settings = Settings()