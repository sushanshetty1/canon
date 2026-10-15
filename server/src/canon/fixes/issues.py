"""A fix as a GitHub issue: the title and Markdown body, and filing it.

`CANON_ISSUES_DRY_RUN` is on unless set to 0: then filing records the issue and returns a fake URL, and nothing
reaches GitHub. Off, the issue is filed with the signed-in user's token in a repository they choose and can push
to, never one of PostHog's.
"""

import os
import re
from urllib.parse import urljoin

import httpx

GITHUB_API = "https://api.github.com"
_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
FOOTER = "Found by Canon, which checks every page against a graph that knows when each fact held."


class FilingError(RuntimeError):
    """GitHub refused or could not be reached. The message is safe to show."""


def dry_run() -> bool:
    return os.environ.get("CANON_ISSUES_DRY_RUN", "1").strip().lower() not in ("0", "false", "no", "off")


def check_repo(repo: str) -> str:
    """`owner/name`, trimmed. Raises ValueError for anything else, and for PostHog's own repositories."""
    repo = (repo or "").strip().removeprefix("https://github.com/").strip("/")
    if not _REPO.match(repo) or repo.endswith(".git"):
        raise ValueError("Name a repository as owner/name.")
    if repo.split("/")[0].lower() == "posthog":
        raise ValueError("Canon never files issues in PostHog's repositories. Choose one of your own.")
    return repo


def _quiet(text: str) -> str:
    """No @mentions: an issue should not ping anyone, so every @ gets a zero-width joiner after it."""
    return (text or "").replace("@", "@⁠")


def _plain(text: str, base: str | None) -> str:
    """One line of page Markdown made safe to quote: relative links made absolute, images dropped, no mentions."""

    def link(m: re.Match) -> str:
        bang, label, href = m.groups()
        if bang:
            return label
        if base and not re.match(r"^[a-z]+:", href):
            href = urljoin(base, href)
        return f"[{label}]({href})"

    return _quiet(" ".join(_LINK.sub(link, text or "").split()))


def _strike(text: str) -> str:
    return f"~~{text.replace('~~', '~ ~')}~~"


def owner_text(routed: list[dict]) -> str:
    """The owner as plain text: the team, then its lead's name and handle. Never an @mention."""
    teams = [r for r in routed if r["kind"] == "team"]
    people = [r for r in routed if r["kind"] == "person"]
    parts = []
    for t in teams:
        leads = [p for p in people if p.get("team") == t["key"]]
        lead = ", ".join(f"{p['name']} ({p['key']})" if p["name"] != p["key"] else p["key"] for p in leads)
        parts.append(f"{t['name']}" + (f", led by {lead}" if lead else ""))
    if not teams:
        parts += [f"{p['name']} ({p['key']})" if p["name"] != p["key"] else p["key"] for p in people]
    return _quiet("; ".join(parts) or "No owner found")


def issue_title(fix: dict) -> str:
    page = fix["page"]["title"] or "A page"
    now = (fix["evidence"][0]["fact"] if fix["evidence"] else "").rstrip(". ")
    return _quiet(f"{page}: {now}" if now else f"{page} is out of date")[:240]


def issue_body(fix: dict) -> str:
    page = fix["page"]
    base = page.get("url")
    lines = [
        f"[{_quiet(page['title'] or 'This page')}]({page['url']}) says something that has since changed.",
        "",
        "**Change this line**",
        "",
        f"> {_strike(_plain(fix['old'], base))}",
        "",
        "**to**",
        "",
        f"> {_plain(fix['new'], base)}",
        "",
        "**Why**",
        "",
    ]
    for e in fix["evidence"]:
        where = f"{e['title']}, {e['date']}" if e.get("date") else e.get("title") or "the source"
        source = f"[{_quiet(where)}]({e['url']})" if e.get("url") else _quiet(where)
        lines.append(f"- {_quiet(e['fact'])} Source: {source}.")
    lines += [
        "",
        f"**Owner:** {owner_text(fix['routed'])}" + (f". {_quiet(fix['reason'])}" if fix.get("reason") else ""),
        "",
        "---",
        "",
        f"_{FOOTER}_",
    ]
    return "\n".join(lines)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "canon",
    }


def file_issue(repo: str, title: str, body: str, *, token: str, transport: httpx.BaseTransport | None = None) -> dict:
    """Files the issue with the user's token. Checks first that the user can push to the repository.
    Returns `{"url", "number"}`. Raises FilingError with a message fit to show."""
    repo = check_repo(repo)
    if not token:
        raise FilingError("Sign in with GitHub to file issues.")
    with httpx.Client(base_url=GITHUB_API, headers=_headers(token), transport=transport, timeout=20) as client:
        try:
            found = client.get(f"/repos/{repo}")
            if found.status_code == 404:
                raise FilingError(f"{repo} was not found, or your GitHub account cannot see it.")
            if found.status_code in (401, 403):
                raise FilingError("GitHub did not accept your sign-in. Sign in again.")
            found.raise_for_status()
            if not (found.json().get("permissions") or {}).get("push"):
                raise FilingError(f"You cannot push to {repo}. Choose a repository you can write to.")
            if found.json().get("has_issues") is False:
                raise FilingError(f"{repo} has issues turned off.")
            made = client.post(f"/repos/{repo}/issues", json={"title": title, "body": body})
            if made.status_code in (401, 403, 404, 410):
                raise FilingError(f"GitHub would not file an issue in {repo}.")
            made.raise_for_status()
        except httpx.HTTPError:
            raise FilingError("GitHub could not be reached. Try again in a moment.") from None
        out = made.json()
    return {"url": out["html_url"], "number": out["number"]}
