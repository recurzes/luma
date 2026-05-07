from __future__ import annotations

import asyncio
import re
from collections import deque
from typing import TYPE_CHECKING

import discord
import httpx
import structlog
from aiohttp import payload

from app.models.member import Member

from app.embeds.github_embed import build_commit_embed, build_pr_embed, build_ci_failure_embed
from app.config import settings

if TYPE_CHECKING:
    from supabase import Client
    from app.services.member_service import MemberService
    from app.services.steak_service import StreakService
    from app.services.xp_service import XPService

from app.services.ticket_service import TicketService

log = structlog.get_logger()

_ANY_RE = re.compile(r'\bany\b')
_COMMENT_LINE_RE = re.compile(r'^\+\s*(?://|/\*|\*)')

_reviewer_queue: deque[str] = deque()


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
        return asyncio.get_event_loop().run_in_executor(None, fn)

    async def get_member_by_github(self, github_username: str) -> Member | None:
        def _fetch():
            return (
                self._db.table("bot_members")
                .select("*")
                .eq("github_username", github_username)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return Member.model_validate(result.data[0])

    # Dispatcher

    async def dispatch(self, event_row: dict) -> None:
        event_type = event_row.get("event_type", "")
        handlers = {
            "push": self.process_push,
            "pull_request": self.process_pull_request,
            "pull_request_review": self.process_review,
            "check_run": self.process_ci
        }
        handler = handlers.get(event_type)
        if handler:
            try:
                await handler(event_row)
            except Exception as e:
                log.error("github.dispatch.error", event_type=event_type, error=str(e))
        else:
            log.debug("github.dispatch.unknown", event_type=event_type)

    # Operations
    async def process_push(self, event_row: dict) -> None:
        payload = event_row.get("payload", {})
        pusher = payload.get("pusher", {}).get("name", event_row.get("actor", "unknown"))
        branch = payload.get("ref", "refs/heads/unknown").replace("refs/heads/", "")
        commits: list[dict] = payload.get("commits", [])

        member = await self.get_member_by_github(pusher)

        if member:
            for _ in commits:
                await self._xp.award(str(member.id), "commit", metadata={"branch": branch})
            await self._streak.record_activity(str(member.id), "commit")

        embed = build_commit_embed(branch=branch, commits=commits, author_member=member)
        await self._post_to_channel("github_feed", embed)
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
        repo_full = pr.get("head", {}).get("repo", {}).get("full_name", "")
        merged = pr.get("merged", False)

        author_member = await self.get_member_by_github(author_login)

        if action == "opened":
            reviewer_member = await self.assign_reviewer(author_member, pr_title)

            embed = build_pr_embed(
                pr_number=pr_number, pr_title=pr_title, pr_url=pr_url,
                author_member=author_member, reviewer_member=reviewer_member
            )
            await self._post_to_channel("github_feed", embed)

            if author_member and author_member.role == "beginner" and settings.GITHUB_TOKEN:
                await self._check_any_usage(repo_full, pr_number, author_member)

            if author_member and author_member.role == "beginner" and settings.GITHUB_TOKEN:
                await self._check_t3_paths(repo_full, pr_number, author_member)

        elif action == "closed" and merged:
            await self._handle_pr_merged(repo_full, pr_number, author_member)

        elif action == "closed" and not merged:
            await self._post_to_channel(
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
        await self._post_to_channel("github_feed", embed)

        if author_member:
            xp_result = await self._xp.award(str(author_member.id), "pr_merged", metadata={"pr_number": pr_number})
            await self._streak.record_activity(str(author_member.id), "pr_merged")
            if xp_result.level_up:
                await self._announce_level_up(author_member, xp_result)

            await self._increment_stat(str(author_member.id), "prs_merged")

        await self._close_linked_ticket(pr_body)

    async def _close_linked_ticket(self, pr_body: str) -> None:
        patterns = [
            re.compile(r'ticket:([a-f0-9]{8})', re.IGNORECASE),
            re.compile(r'[Cc]loses?\s+#([a-f0-9]{8})'),
        ]
        for pattern in patterns:
            match = pattern.search(pr_body)
            if match:
                short_id = match.group(1)
                try:
                    svc = TicketService(self._db, self._members)
                    result = await svc.close(short_id, "github-bot")
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

        reviewer_member = await self.get_member_by_github(reviewer_login)

        embed = _simple_embed(
            f"PR #{pr.get('number')} reviewed",
            f"**{reviewer_login}** submitted a **{state}** review on [{pr.get('title')}]({pr.get('html_url')})",
            0x5865F2,
        )
        await self._post_to_channel("github_feed", embed)

        if reviewer_member:
            await self._xp.award(str(reviewer_member.id), "pr_reviewed", metadata={"pr_number": pr.get("number")})
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
        await self._post_to_channel("github_feed", embed)

    # TS `any` guard

    async def _check_any_usage(self, repo_full: str, pr_number: int, author: Member) -> None:
        files = await self._fetch_pr_files(repo_full, pr_number)
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

        if violations:
            lines = [f"- `{fn}` (+{n}) occurrence{'s' if n > 1 else ''}" for fn, n in violations.items()]
            embed = discord.Embed(
                title=f"⚠️ PR #{pr_number} — TypeScript `any` detected",
                description=f"**{author.discord_name}**'s PR contains `any` usage:\n" + "\n".join(
                    lines) + "\n\nAction: review before merging",
                color=discord.Color.yellow()
            )
            await self._post_to_channel("code_review", embed)

    async def _check_t3_paths(self, repo_full: str, pr_number: int, author: Member):
        files = await self._fetch_pr_files(repo_full, pr_number)
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
            await self._post_to_channel("code_review", embed)

    # Review Rotation
    async def assign_reviewer(self, author_member: Member | None, pr_title: str) -> Member | None:
        all_members = await self._members.get_all_active()

        tier_match = re.search(r'\[T([123])\]', pr_title, re.IGNORECASE)
        pr_tier = f"T{tier_match.group(1)}" if tier_match else "T1"

        candidates = [
            m for m in all_members
            if (author_member is None or m.id != author_member.id)
               and (pr_tier == "T1" or m.role in ("lead", "professor"))
        ]
        if not candidates:
            return None

        global _reviewer_queue
        if not _reviewer_queue or set(str(m.id) for m in candidates) != set(_reviewer_queue):
            _reviewer_queue = deque(str(m.id) for m in candidates)

        next_id = _reviewer_queue[0]
        _reviewer_queue.rotate(-1)
        return next((m for m in candidates if str(m.id) == next_id), candidates[0])

    # Helpers

    async def _fetch_pr_files(self, repo_full: str, pr_number: int) -> list[dict]:
        if not settings.GITHUB_TOKEN:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/files",
                    headers={"Authorization": f"toke {settings.GITHUB_TOKEN}",
                             "Accept": "application/vnd.github.v3+json"}
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            log.warning("github.fetch_pr_files.error", error=str(e))

        return []

    async def _post_to_channel(self, channel_key: str, embed) -> None:
        if self._bot is None:
            return
        channel_map = {
            "github_feed": settings.CHANNEL_GITHUB_FEED,
            "code_review": settings.CHANNEL_CODE_REVIEW,
            "shoutouts": settings.CHANNEL_SHOUTOUTS
        }
        channel_id = channel_map.get(channel_key)
        if channel_id is None:
            return
        guild = self._bot.get_guild(settings.DISCORD_GUILD_ID)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=embed)

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
        await self._post_to_channel("shoutouts", embed)


def _simple_embed(title: str, description: str, color: int):
    return discord.Embed(title=title, description=description, color=color)
