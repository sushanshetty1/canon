"""Reads one RFC: its status, what it decided, the RFCs it names, its areas, and the pull requests that build it.

Everything here is plain text work over raw RFC rows and pull request rows. No graph, no model. An RFC row is one of:

- an RFC on the main branch, as the PostHog connector caches it (`rfcs.json`: path, text, dates, and the pull request
  that added the file);
- a proposal: an RFC pull request that never merged, open or closed (`rfc_proposals.json`, see
  `canon.decisions.build.rfc_proposals`), with `proposal: {state, closed_at, url, title}`.

An RFC is accepted when its pull request merged (or it was committed to the main branch directly), proposed while
its pull request is open, and withdrawn when the pull request closed without merging.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

STATUSES = ("proposed", "accepted", "withdrawn", "rejected", "retired", "superseded")

# The RFC says of itself that it no longer describes how things work.
_RETIRED = re.compile(
    r"this rfc is (now )?(out of date|outdated|obsolete|deprecated|no longer)|(contents|it) (do|does) not reflect how", re.I
)
# "Decision: no", "> **Decision:** rejected", "Decision: we will not ..."
_REJECTED = re.compile(r"\bdecision\b\**\s*:+\**\s*(no\b|rejected|not\b|we (will not|won't|decided not))", re.I)
# A decision line near the top: "Decision:", "> **Decision:**", "**Decision: Yes, ...**". Not "Decision date:".
_DECISION_LINE = re.compile(r"^\s*>?\s*\**\s*decision\s*:+\**\s*:?\s*(.+?)\**\s*$", re.I | re.M)
_TLDR_LINE = re.compile(r"^\s*>?\s*\**\s*tl;?dr\s*:+\**\s*(.+?)\s*$", re.I | re.M)
# Words that say one thing replaces another, in the sentence that names the other RFC.
REPLACES = re.compile(r"\b(supersed\w*|replac\w*|instead of|in favou?r of|obsolete\w*|deprecat\w*|fold(s|ed|ing)?)\b", re.I)
NEAR = 80  # a replacement word counts when it is this close to the link

_RFC_FILE = re.compile(r"(?:requests-for-comments/|\./)([\w.%-]+?)\.md", re.I)
_RFC_PULL = re.compile(r"requests-for-comments-public/pull/(\d+)", re.I)


def decision_id(path: str) -> str:
    """`requests-for-comments/2026-07-24-wizard-v2.5.md` -> `2026-07-24-wizard-v2-5`."""
    stem = PurePosixPath(path).stem
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def day(iso: str | None) -> str | None:
    return (iso or "")[:10] or None


@dataclass
class Rfc:
    id: str
    path: str
    doc_id: str
    text: str
    stem: str
    proposed_at: str | None
    decided_at: str | None
    updated_at: str | None
    pr_number: int | None
    merged_by: str | None
    state: str = "merged"  # merged | main (committed without a pull request) | open | closed
    closed_at: str | None = None
    url: str | None = None  # where a proposal can be read: its pull request
    pr_title: str | None = None
    approvers: list[tuple[str, str]] = field(default_factory=list)  # (handle, at)


def from_row(row: dict) -> Rfc:
    pr = row.get("pr") or {}
    approvers = [
        (r["author"], day(r.get("at")) or "")
        for r in pr.get("reviews") or []
        if r.get("state") == "APPROVED" and r.get("author")
    ]
    seen: dict[str, str] = {}
    for handle, at in approvers:
        seen.setdefault(handle.lower(), at)
    proposed = min(d for d in (day(pr.get("created_at")), day(row.get("created_at"))) if d) if (
        pr.get("created_at") or row.get("created_at")
    ) else None
    proposal = row.get("proposal") or {}
    if proposal:
        state = "open" if proposal.get("state") == "OPEN" else "closed"
    else:
        state = "merged" if pr.get("merged_at") else "main"
    decided = day(pr.get("merged_at")) or (day(row.get("created_at")) if state == "main" else None)
    return Rfc(
        id=decision_id(row["path"]),
        path=row["path"],
        doc_id=f"rfc:{row['path']}",
        text=row.get("text") or "",
        stem=PurePosixPath(row["path"]).stem,
        proposed_at=proposed,
        decided_at=decided,
        updated_at=day(row.get("updated_at")),
        pr_number=pr.get("number"),
        merged_by=(pr.get("merged_by") or "").lower() or None,
        state=state,
        closed_at=day(proposal.get("closed_at")),
        url=proposal.get("url"),
        pr_title=proposal.get("title"),
        approvers=sorted(seen.items()),
    )


def status_of(rfc: Rfc) -> str:
    """What the RFC's own text and its pull request say. Replacement by a later RFC is decided by the graph."""
    head = rfc.text[:4000]
    if _RETIRED.search(head):
        return "retired"
    if _REJECTED.search(head):
        return "rejected"
    return {"merged": "accepted", "main": "accepted", "open": "proposed", "closed": "withdrawn"}[rfc.state]


def _plain(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"[*_`#>]+", "", line)
    return " ".join(line.replace("—", ",").replace("–", "-").split()).strip(" -:")


def _clip(text: str, limit: int = 260) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "..."


def summary_of(text: str) -> str:
    """The RFC's own decision line when it has one, else its TL;DR, else its first paragraph of prose."""
    head = "\n".join(text.splitlines()[:60])
    for pattern in (_DECISION_LINE, _TLDR_LINE):
        m = pattern.search(head)
        if m:
            value = _plain(m.group(1))
            if len(value) > 12 and not re.match(r"(date|maker)", value, re.I):
                return _clip(value)
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        # Headings, metadata lists, template prompts, notes to reviewers, tables, images and code are not prose.
        if re.match(r"^(#|[-*+]\s|\d+\.\s|\||!\[|```|<)", first) or re.match(r"^\s*>", first):
            continue
        if re.match(r"^[_*].*[_*]$", first) or re.match(r"^\**(owner|author|date|created|deadline|pr|decider|decision date|decision maker|status)\b", first, re.I):
            continue
        prose = _plain(" ".join(lines))
        if len(prose) > 40:
            return _clip(prose)
    return ""


@dataclass(frozen=True)
class Reference:
    target: str  # a decision id
    context: str  # the sentence that names it
    replaces: bool  # the sentence uses replacement words


def references(rfc: Rfc, known: dict[str, "Rfc"]) -> list[Reference]:
    """The other RFCs this one names, by file name or by the pull request that added them."""
    by_stem = {r.stem.lower(): r.id for r in known.values()}
    by_pr = {r.pr_number: r.id for r in known.values() if r.pr_number}
    found: dict[str, Reference] = {}
    for line in rfc.text.splitlines():
        links = [(m, by_stem.get(m.group(1).replace("%20", " ").lower())) for m in _RFC_FILE.finditer(line)]
        links += [(m, by_pr.get(int(m.group(1)))) for m in _RFC_PULL.finditer(line)]
        for m, target in links:
            if not target or target == rfc.id:
                continue
            near = line[max(0, m.start() - NEAR) : m.end() + NEAR]
            ref = Reference(target, _clip(_plain(line), 300), bool(REPLACES.search(near)))
            if target not in found or (ref.replaces and not found[target].replaces):
                found[target] = ref
    return list(found.values())


# ----- areas -----------------------------------------------------------------------------------------------------

# Words an RFC uses for an area that its name in the ownership map does not contain. Hand-checked against the 44
# public RFCs; a phrase maps to one area slug.
ALIASES: dict[str, tuple[str, ...]] = {
    "feature-flags": ("feature flag", "feature flags", "flag", "flags", "decide"),
    "replay": ("session replay", "recordings", "recording"),
    "experimentation": ("a/b testing", "a/b tests", "experiments"),
    "sso": ("saml", "single sign-on"),
    "permissions": ("rbac", "access control", "access controls"),
    "group-analytics": ("groups",),
    "persons": ("person model", "persons", "person properties"),
    "surveys": ("nps", "survey"),
    "ingestion": ("capture", "kafka", "warpstream", "msk"),
    "sdks": ("sdk", "sdks", "posthog-js"),
    "billing": ("plans", "pricing"),
    "insights": ("insight", "query schema"),
    "data-table": ("data tables",),
    "batch-exports": ("exports",),
    "PostHog.com": ("posthog.com", "docs", "website", "tutorials", "blog", "llms.txt"),
    "health-alerts": ("health page", "health checks", "health issues"),
    "query-performance": ("rate limits", "rate limiting"),
    "cohorts": ("cohort",),
    "internal-messaging": ("emails",),
    "self-hosting": ("self-hosted",),
}
# Names that are everyday words in an RFC ("SAML support", "AI search"): only these phrases name the area.
EXACT: dict[str, tuple[str, ...]] = {
    "support": ("customer support", "support team", "support tickets", "support engineers", "zendesk"),
    "search": ("global search", "search bar"),
    "comments": ("discussions",),
    "settings": ("project settings", "personal settings", "organization settings"),
    "tasks": ("posthog tasks",),
    "platform": ("platform team",),
    "signals": ("inbox",),
    "feed": ("activity feed",),
    "variables": ("sql variables", "insight variables"),
    "workflows": ("posthog workflows",),
    "cli": ("posthog cli",),
}
# Broad areas a body names in passing: only many mentions, or the title, make an RFC about them.
BROAD = frozenset(
    {"actions", "alerts", "integrations", "messaging", "security", "subscriptions", "onboarding", "billing",
     "ingestion", "PostHog.com", "internal-messaging", "endpoints", "dashboards"}
)
TITLE_WEIGHT = 6
MIN_BODY = 6  # mentions in the body that make an RFC about an area its title does not name
BROAD_BODY = 14
SHARE = 0.4  # ... and at least this share of the mentions of its most-named area
MAX_AREAS = 3


def _phrases(slug: str, name: str) -> set[str]:
    if slug in EXACT:
        return set(EXACT[slug])
    out = {re.sub(r"\s*\(.*?\)", "", name).strip().lower(), slug.replace("-", " ").lower()}
    out |= set(ALIASES.get(slug, ()))
    return {p for p in out if len(p) >= 3}


def _count(phrase: str, text: str) -> int:
    return len(re.findall(rf"(?<![\w/-]){re.escape(phrase)}(?![\w-])", text))


def areas_of(title: str, text: str, areas: dict[str, str]) -> list[str]:
    """Area slugs the RFC is about, best first. The title names its areas; the body adds an area it names often."""
    title_l, body_l = title.lower(), text.lower()
    counts: dict[str, tuple[int, int]] = {}
    for slug, name in areas.items():
        phrases = _phrases(slug, name)
        counts[slug] = (sum(_count(p, title_l) for p in phrases), sum(_count(p, body_l) for p in phrases))
    top = max((b for _, b in counts.values()), default=0)
    chosen = {}
    for slug, (in_title, in_body) in counts.items():
        floor = BROAD_BODY if slug in BROAD else MIN_BODY
        if in_title or (in_body >= floor and in_body >= SHARE * top):
            chosen[slug] = TITLE_WEIGHT * min(in_title, 1) + in_body
    return sorted(chosen, key=lambda s: (-chosen[s], s))[:MAX_AREAS]


# ----- pull requests that build an RFC ---------------------------------------------------------------------------


def pull_id(row: dict) -> str:
    """Pull requests in PostHog's main repo keep the connector's id (`pull:123`); others name their repo."""
    repo = row.get("repo") or "PostHog/posthog"
    return f"pull:{row['number']}" if repo == "PostHog/posthog" else f"pull:{repo}#{row['number']}"


def links_rfc(rfc: Rfc, body: str) -> bool:
    body = body or ""
    if rfc.stem and rfc.stem in body:
        return True
    return bool(rfc.pr_number) and any(int(m.group(1)) == rfc.pr_number for m in _RFC_PULL.finditer(body))


def names_rfc(title: str, body: str) -> bool:
    """A pull request that names an RFC by its title, and says it is an RFC."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    if len(words) < 2:
        return False
    return bool(re.search(r"\brfc\b", body, re.I)) and title.lower() in body.lower()


def implemented_by(rfc: Rfc, title: str, pulls: list[dict]) -> list[tuple[dict, str]]:
    """Merged pull requests that link the RFC (`how` = 'link') or name it by title (`how` = 'title')."""
    out = []
    for p in pulls:
        if not p.get("merged_at"):
            continue
        text = f"{p.get('title') or ''}\n{p.get('body') or ''}"
        if links_rfc(rfc, text):
            out.append((p, "link"))
        elif names_rfc(title, text):
            out.append((p, "title"))
    return out
