from __future__ import annotations

import asyncio
import re
from collections import deque
from typing import TYPE_CHECKING

import discord
import httpx
import structlog
from datetime import datetime, timezone

from app.models.member import Member

from app.embeds.github_embed import build_commit_embed, build_pr_embed, build_ci_failure_embed
from app.config import settings
from app.channels import CHANNEL_MANIFEST

if TYPE_CHECKING:
    from supabase import Client
    from app.services.member_service import MemberService
    from app.services.steak_service import StreakService
    from app.services.xp_service import XPService

from app.services.ticket_service import TicketService
from app.services.badge_service import BadgeService
from app.utils.badge_broadcast import get_current_streak, post_badges_to_shoutouts
from app.utils.github_repo import normalize_repo

log = structlog.get_logger()

_ANY_RE = re.compile(r'\bany\b')
_COMMENT_LINE_RE = re.compile(r'^\+\s*(?://|/\*|\*)')

MAX_EVENT_ATTEMPTS = 5

_FILES_PER_PAGE = 100
_MAX_FILE_PAGES = 10

UNLINKED_REPO = "repo not linked to a project in any server"

# Reviewer rotation per server: guild id -> queue of member ids.
_reviewer_queues: dict[str, deque[str]] = {}


class GitHubService:
    def __init__(
            self,
            db: "Client",
            members: "MemberService",
            xp: "XPService",
            streak: "StreakService",
            bot=None
    ) -> None:
        self._db = db
        self._members = members
        self._xp = xp
        self._streak = streak
        self._bot = bot

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def _upsert_pr_reviewer_row(
            self,
            guild_id: str,
            repo_full_name: str,
            pr_number: int,
            reviewer_member_id: str,
            pr_url: str,
            pr_created_at: str
    ) -> None:
        row = {
            "guild_id": guild_id,
            "repo_full_name": repo_full_name,
            "pr_number": pr_number,
            "reviewer_member_id": reviewer_member_id,
            "pr_url": pr_url,
            "pr_created_at": pr_created_at,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        def _upsert():
            return (
                self._db.table("bot_pr_reviewers")
                .upsert(row, on_conflict="guild_id,repo_full_name,pr_number")
                .execute()
            )

        await self._run(_upsert)
        log.info("github.pr_reviewer_map.upserted", pr_number=pr_number)

    async def _delete_pr_reviewer_ro(self, guild_id: str, repo_full_name: str, pr_number: int) -> None:
        def _delete():
            return (
                self._db.table("bot_pr_reviewers")
                .delete()
                .eq("guild_id", guild_id)
                .eq("repo_full_name", repo_full_name)
                .eq("pr_number", pr_number)
                .execute()
            )

        await self._run(_delete)

    async def get_member_by_github(self, github_username: str, guild_id: str) -> Member | None:
        if not github_username:
            return None

        def _fetch():
            return (
                self._db.table("bot_members")
                .select("*")
                .eq("guild_id", guild_id)
                .ilike("github_username", _escape_like(github_username))
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return Member.model_validate(result.data[0])

    # Dispatcher

    async def guilds_for_repo(self, repo_full_name: str) -> list[str]:
        """Servers with an active project linked to this repository (`/project link-repo`)."""
        wanted = normalize_repo(repo_full_name)
        if wanted is None:
            return []

        def _fetch():
            return (
                self._db.table("companion_projects")
                .select("discord_guild_id, github_repo_url")
                .eq("status", "active")
                .not_.is_("github_repo_url", "null")
                .execute()
            )

        rows = (await self._run(_fetch)).data
        return sorted({
            r["discord_guild_id"] for r in rows
            if normalize_repo(r.get("github_repo_url")) == wanted
        })

    async def dispatch(self, event_row: dict) -> list[str] | None:
        """Run the handler once per server the event's repo is linked to.

        Returns the servers it was routed to, or None for an event type the bot ignores.
        An empty list means no server has linked the repository.
        """
        event_type = event_row.get("event_type", "")
        handlers = {
            "push": self.process_push,
            "pull_request": self.process_pull_request,
            "pull_request_review": self.process_review,
            "check_run": self.process_ci
        }
        handler = handlers.get(event_type)
        if handler is None:
            log.debug("github.dispatch.unknown", event_type=event_type)
            return None

        repo = ((event_row.get("payload") or {}).get("repository") or {}).get("full_name", "")
        guild_ids = await self.guilds_for_repo(repo)
        for guild_id in guild_ids:
            # Errors propagate so process_pending can leave the event queued for a retry.
            await handler({**event_row, "guild_id": guild_id, "repo_full_name": normalize_repo(repo)})
        return guild_ids

    # Event queue: bot_github_events rows stay pending until a handler finishes cleanly.

    async def fetch_pending_events(self, limit: int = 50) -> list[dict]:
        def _fetch():
            return (
                self._db.table("bot_github_events")
                .select("*")
                .is_("processed_at", "null")
                .lt("attempts", MAX_EVENT_ATTEMPTS)
                .order("received_at", desc=False)
                .limit(limit)
                .execute()
            )

        return (await self._run(_fetch)).data

    async def _mark_event(self, event_id: str, fields: dict) -> None:
        def _update():
            return (
                self._db.table("bot_github_events")
                .update(fields)
                .eq("id", event_id)
                .execute()
            )

        await self._run(_update)

    async def process_pending(self, limit: int = 50) -> tuple[int, int]:
        """Dispatch pending events oldest first. Returns (processed, failed)."""
        processed = failed = 0
        for event in await self.fetch_pending_events(limit):
            event_id = event["id"]
            try:
                routed = await self.dispatch(event)
            except Exception as e:
                attempts = (event.get("attempts") or 0) + 1
                failed += 1
                log.error(
                    "github.dispatch.error",
                    event_id=event_id,
                    event_type=event.get("event_type"),
                    attempts=attempts,
                    gave_up=attempts >= MAX_EVENT_ATTEMPTS,
                    error=str(e)
                )
                await self._mark_event(event_id, {"attempts": attempts, "last_error": str(e)[:500]})
                continue

            done: dict = {"processed_at": datetime.now(timezone.utc).isoformat()}
            if routed:
                done["guild_id"] = ",".join(routed)
            elif routed is not None:
                done["last_error"] = UNLINKED_REPO
                log.info("github.dispatch.unlinked_repo", event_id=event_id, event_type=event.get("event_type"))
            await self._mark_event(event_id, done)
            processed += 1
        return processed, failed

    # Operations
    async def process_push(self, event_row: dict) -> None:
        payload = event_row.get("payload", {})
        pusher = payload.get("pusher", {}).get("name", event_row.get("actor", "unknown"))
        branch = payload.get("ref", "refs/heads/unknown").replace("refs/heads/", "")
        commits: list[dict] = payload.get("commits", [])

        guild_id = event_row["guild_id"]
        member = await self.get_member_by_github(pusher, guild_id)

        if member:
            for commit in commits:
                await self._xp.award(
                    str(member.id), "commit", metadata={"branch": branch},
                    dedupe_key=_event_key(event_row, commit.get("id"))
                )
            await self._streak.record_activity(str(member.id), "commit")

            streak_n = await get_current_streak(self._db, str(member.id))
            push_badges = await BadgeService(self._db, self._xp).check_and_award(
                str(member.id), "streak_check", {"current_streak": streak_n}
            )
            await post_badges_to_shoutouts(self._bot, member, push_badges)

        embed = build_commit_embed(branch=branch, commits=commits, author_member=member)
        await self._post_to_channel(guild_id, "github_feed", embed)
        log.info("github.push.processed", pusher=pusher, commits=len(commits))

    # PR
    async def process_pull_request(self, event_row: dict) -> None:
        payload = event_row.get("payload", {})
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")
        pr_title = pr.get("title", "")
        pr_url = pr.get("html_url", "")
        pr_body = pr.get("body") or ""
        author_login = pr.get("user", {}).get("login", event_row.get("actor", ""))
        # The files endpoint lives on the base repo; head differs for fork PRs.
        repo_full = ((pr.get("base") or {}).get("repo") or pr.get("head", {}).get("repo") or {}).get("full_name", "")
        merged = pr.get("merged", False)

        guild_id = event_row["guild_id"]
        repo_key = event_row.get("repo_full_name") or normalize_repo(repo_full) or ""
        author_member = await self.get_member_by_github(author_login, guild_id)

        if action == "closed" and pr_number is not None:
            await self._delete_pr_reviewer_ro(guild_id, repo_key, pr_number)

        if action == "opened":
            reviewer_member = await self.assign_reviewer(guild_id, author_member, pr_title)

            embed = build_pr_embed(
                pr_number=pr_number, pr_title=pr_title, pr_url=pr_url,
                author_member=author_member, reviewer_member=reviewer_member
            )
            await self._post_to_channel(guild_id, "github_feed", embed)

            if reviewer_member is not None and pr_number is not None:
                created = pr.get("created_at") or datetime.now(timezone.utc).isoformat()
                await self._upsert_pr_reviewer_row(
                    guild_id=guild_id,
                    repo_full_name=repo_key,
                    pr_number=int(pr_number),
                    reviewer_member_id=str(reviewer_member.id),
                    pr_url=pr_url,
                    pr_created_at=created
                )

            if author_member and author_member.role == "beginner" and settings.GITHUB_TOKEN:
                await self._check_any_usage(repo_full, pr_number, author_member)
                await self._check_t3_paths(repo_full, pr_number, author_member)

        elif action == "closed" and merged:
            await self._handle_pr_merged(event_row, pr, author_member, pr_body)

        elif action == "closed" and not merged:
            await self._post_to_channel(
                guild_id,
                "github_feed",
                _simple_embed(f"PR #{pr_number} closed (not merged)", pr_title, 0x808080)
            )

        log.info("github.pr.processed", action=action, pr_number=pr_number)

    async def _handle_pr_merged(self, event_row: dict, pr: dict, author_member: Member | None, pr_body: str) -> None:
        pr_number = pr.get("number")
        pr_title = pr.get("title", "")
        pr_url = pr.get("html_url", "")

        embed = build_pr_embed(
            pr_number=pr_number, pr_title=pr_title, pr_url=pr_url,
            author_member=author_member, reviewer_member=None, merged=True
        )
        guild_id = event_row["guild_id"]
        await self._post_to_channel(guild_id, "github_feed", embed)

        if author_member:
            # any_flag feeds the No `any` Club badge: False = scanned and clean, None = not scanned.
            repo_full = (pr.get("base") or {}).get("repo", {}).get("full_name", "")
            files = await self._fetch_pr_files(repo_full, pr_number)
            any_flag = None if files is None else bool(_count_any_violations(files))

            xp_result = await self._xp.award(
                str(author_member.id), "pr_merged", metadata={"pr_number": pr_number, "any_flag": any_flag},
                dedupe_key=_event_key(event_row)
            )
            await self._streak.record_activity(str(author_member.id), "pr_merged")
            if xp_result.level_up:
                await self._announce_level_up(author_member, xp_result)

            if not xp_result.duplicate:
                await self._increment_stat(str(author_member.id), "prs_merged")

            badges = await BadgeService(self._db, self._xp).check_and_award(
                str(author_member.id),
                "pr_merged",
                {"pr_opened_at": pr.get("created_at"), "pr_merged_at": pr.get("merged_at")}
            )
            await post_badges_to_shoutouts(self._bot, author_member, badges)

        await self._close_linked_ticket(pr_body, guild_id)

    async def _close_linked_ticket(self, pr_body: str, guild_id: str) -> None:
        patterns = [
            re.compile(r'ticket:([a-f0-9]{8})', re.IGNORECASE),
            re.compile(r'[Cc]loses?\s+#([a-f0-9]{8})'),
        ]
        for pattern in patterns:
            match = pattern.search(pr_body)
            if match:
                short_id = match.group(1)
                try:
                    svc = TicketService(
                        self._db, self._members, guild_id, xp_service=self._xp, streak_service=self._streak
                    )
                    result = await svc.close(short_id.lower(), "github-bot")
                    if result.awarded_to:
                        await post_badges_to_shoutouts(self._bot, result.awarded_to, result.badges)
                    log.info("github.linked_ticket.closed", short_id=short_id)
                    return
                except Exception as e:
                    log.warning("github.linked_ticket.close_failed", short_id=short_id, error=str(e))

    # Review

    async def process_review(self, event_row: dict) -> None:
        payload = event_row.get("payload", {})
        review = payload.get("review", {})
        pr = payload.get("pull_request", {})
        reviewer_login = review.get("user", {}).get("login", "")
        state = review.get("state", "").lower()

        guild_id = event_row["guild_id"]
        reviewer_member = await self.get_member_by_github(reviewer_login, guild_id)

        embed = _simple_embed(
            f"PR #{pr.get('number')} reviewed",
            f"**{reviewer_login}** submitted a **{state}** review on [{pr.get('title')}]({pr.get('html_url')})",
            0x5865F2,
        )
        await self._post_to_channel(guild_id, "github_feed", embed)

        if reviewer_member:
            xp_result = await self._xp.award(
                str(reviewer_member.id), "pr_reviewed", metadata={"pr_number": pr.get("number")},
                dedupe_key=_event_key(event_row)
            )
            if not xp_result.duplicate:
                await self._increment_stat(str(reviewer_member.id), "helps_given")

    # CI

    async def process_ci(self, event_row: dict) -> None:
        payload = event_row.get("payload", {})
        check = payload.get("check_run", {})
        conclusion = check.get("conclusion", "")
        if conclusion not in ("failure", "timed_out", "cancelled"):
            return

        name = check.get("name", "CI")
        url = check.get("html_url", "")
        embed = build_ci_failure_embed(check_name=name, conclusion=conclusion, url=url)
        await self._post_to_channel(event_row["guild_id"], "github_feed", embed)

    # TS `any` guard

    async def _check_any_usage(self, repo_full: str, pr_number: int, author: Member) -> None:
        files = await self._fetch_pr_files(repo_full, pr_number) or []
        violations = _count_any_violations(files)

        if violations:
            lines = [f"- `{fn}` (+{n}) occurrence{'s' if n > 1 else ''}" for fn, n in violations.items()]
            embed = discord.Embed(
                title=f"⚠️ PR #{pr_number} — TypeScript `any` detected",
                description=f"**{author.discord_name}**'s PR contains `any` usage:\n" + "\n".join(
                    lines) + "\n\nAction: review before merging",
                color=discord.Color.yellow()
            )
            await self._post_to_channel(author.guild_id, "code_review", embed)

    async def _check_t3_paths(self, repo_full: str, pr_number: int, author: Member):
        files = await self._fetch_pr_files(repo_full, pr_number) or []
        protected_hits: list[str] = []

        for f in files:
            filename: str = f.get("filename", "")
            for path_prefix in settings.T3_PROTECTED_PATHS:
                if filename.startswith(path_prefix) or filename == path_prefix:
                    protected_hits.append(filename)
                    break

        if protected_hits:
            lines = [f"- `{f}`" for f in protected_hits]
            embed = discord.Embed(
                title=f"⚠️ PR #{pr_number} — Architect-tier files modified",
                description=f"**{author.discord_name}**'s PR touches protected paths:\n" + "\n".join(
                    lines) + "\n\nAction required: verbal walkthrough before merge.",
                color=discord.Color.red(),
            )
            await self._post_to_channel(author.guild_id, "code_review", embed)

    # Review Rotation
    async def assign_reviewer(self, guild_id: str, author_member: Member | None, pr_title: str) -> Member | None:
        all_members = await self._members.get_all_active(guild_id)

        tier_match = re.search(r'\[T([123])\]', pr_title, re.IGNORECASE)
        pr_tier = f"T{tier_match.group(1)}" if tier_match else "T1"

        candidates = [
            m for m in all_members
            if (author_member is None or m.id != author_member.id)
               and (pr_tier == "T1" or m.role in ("lead", "professor"))
        ]
        if not candidates:
            return None

        queue = _reviewer_queues.get(guild_id)
        if not queue or set(str(m.id) for m in candidates) != set(queue):
            queue = _reviewer_queues[guild_id] = deque(str(m.id) for m in candidates)

        next_id = queue[0]
        queue.rotate(-1)
        return next((m for m in candidates if str(m.id) == next_id), candidates[0])

    # Helpers

    async def _fetch_pr_files(self, repo_full: str, pr_number: int) -> list[dict] | None:
        """All changed files of a PR, or None when they could not be fetched."""
        if not settings.GITHUB_TOKEN or not repo_full:
            return None

        files: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for page in range(1, _MAX_FILE_PAGES + 1):
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/files",
                        params={"per_page": _FILES_PER_PAGE, "page": page},
                        headers={"Authorization": f"token {settings.GITHUB_TOKEN}",
                                 "Accept": "application/vnd.github.v3+json"}
                    )
                    if resp.status_code != 200:
                        log.warning(
                            "github.fetch_pr_files.bad_status",
                            status=resp.status_code,
                            repo=repo_full,
                            pr_number=pr_number
                        )
                        return None
                    batch = resp.json()
                    files.extend(batch)
                    if len(batch) < _FILES_PER_PAGE:
                        break
        except Exception as e:
            log.warning("github.fetch_pr_files.error", error=str(e))
            return None

        return files

    async def _post_to_channel(self, guild_id: str, channel_key: str, embed) -> None:
        if self._bot is None:
            return
        guild = self._bot.get_guild(int(guild_id))
        if guild is None:
            return
        channel_name = CHANNEL_MANIFEST.get(channel_key, (None, None))[0]
        channel = None
        if hasattr(self._bot, "get_text_channel"):
            channel = self._bot.get_text_channel(channel_key, guild)
        if channel is None and channel_name:
            channel = discord.utils.get(guild.text_channels, name=channel_name)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=embed)
            log.info("github.posted", channel=channel_key, guild_id=guild_id)

    async def _increment_stat(self, member_id: str, field: str) -> None:
        def _fetch():
            return (
                self._db.table("bot_member_stats")
                .select(field)
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        current = result.data[0].get(field, 0) if result.data else 0

        def _update():
            return (
                self._db.table("bot_member_stats")
                .update({field: current + 1})
                .eq("member_id", member_id)
                .execute()
            )

        await self._run(_update)

    async def _announce_level_up(self, member: Member, xp_result) -> None:
        embed = discord.Embed(
            title="Level Up!",
            description=f"**{member.discord_name}** reached level {xp_result.new_level}",
            color=discord.Color.gold()
        )
        await self._post_to_channel(member.guild_id, "shoutouts", embed)


def _escape_like(value: str) -> str:
    """Match a string literally in ILIKE (GitHub logins are case-insensitive)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _event_key(event_row: dict, part: str | None = None) -> str | None:
    """XP dedupe key for a stored event, so a retried event cannot award twice."""
    event_id = event_row.get("id")
    if event_id is None:
        return None
    return f"{event_id}:{part}" if part else str(event_id)


def _count_any_violations(files: list[dict]) -> dict[str, int]:
    """Added `any` occurrences per TypeScript file, ignoring comment lines."""
    violations: dict[str, int] = {}
    for f in files:
        filename: str = f.get("filename", "")
        if not filename.endswith((".ts", ".tsx")):
            continue
        patch: str = f.get("patch", "") or ""
        count = 0
        for line in patch.splitlines():
            if not line.startswith("+"):
                continue
            if _COMMENT_LINE_RE.match(line):
                continue
            count += len(_ANY_RE.findall(line))
        if count:
            violations[filename] = count
    return violations


def _simple_embed(title: str, description: str, color: int):
    return discord.Embed(title=title, description=description, color=color)
