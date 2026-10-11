from __future__ import annotations

import re

_REPO_RE = re.compile(
    r"^(?:(?:https?://|git@|ssh://git@)?(?:www\.)?github\.com[/:])?"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


def normalize_repo(value: str | None) -> str | None:
    """Reduce a GitHub URL or `owner/repo` to lowercase `owner/repo`, or None if it is neither.

    GitHub webhooks identify a repository as `owner/repo`; projects store whatever a Lead
    typed into `/project link-repo`. Both sides go through this so they can be compared.
    """
    if not value:
        return None
    match = _REPO_RE.match(value.strip())
    if not match:
        return None
    return f"{match['owner']}/{match['repo']}".lower()
