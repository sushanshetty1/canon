"""The shapes every part of Canon passes to every other part. Connectors produce them, the writer stores them."""

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal[
    "handbook", "doc", "team_page", "ownership_map", "rfc", "adr", "wiki", "release", "notion", "confluence",
    "issue", "pull", "forum", "discussion", "thread", "slack",
]
Verdict = Literal["verified", "stale", "disputed", "unsupported"]
ActivityRel = Literal["AUTHORED", "REVIEWED", "COMMENTED", "DECIDED"]


@dataclass(frozen=True)
class Doc:
    id: str  # stable: f"{kind}:{path or number}"
    kind: Kind
    title: str
    url: str  # a public URL a reader can open
    updated_at: str  # ISO date of the version read
    author: str | None = None  # GitHub handle when known
    areas: tuple[str, ...] = ()  # area slugs the document is about, e.g. from a pull request's `feature/*` label
    decided_at: str | None = None  # for an RFC: the date it was accepted, which is when its facts start to hold


@dataclass(frozen=True)
class Passage:
    id: str  # f"{doc_id}#{index}"
    doc_id: str
    text: str
    # A turn in a conversation (a comment, a chat message, a forum reply) says who said it and when. The author is
    # a person's handle (a GitHub handle, or `name:<slug>` for someone known only by name), or None.
    author: str | None = None
    at: str | None = None  # ISO date the words were written; a fact stated here starts to hold then


@dataclass(frozen=True)
class Fact:
    id: str
    subject: str  # an entity key: "area:notebooks", "team:replay", "person:timgl", "topic:friday-deploys"
    predicate: str
    value: str  # an entity key or a short phrase
    text: str  # the fact as one plain sentence
    valid_from: str  # ISO date
    passage_id: str
    authority: int
    valid_to: str | None = None


@dataclass(frozen=True)
class Person:
    handle: str
    name: str
    role: str | None = None


@dataclass(frozen=True)
class Team:
    slug: str
    name: str
    members: tuple[str, ...] = ()
    leads: tuple[str, ...] = ()


@dataclass(frozen=True)
class Area:
    slug: str
    name: str


@dataclass(frozen=True)
class Activity:
    """Who did what to which document."""

    handle: str
    doc_id: str
    rel: ActivityRel
    at: str


@dataclass
class Batch:
    """What a connector returns."""

    docs: list[Doc] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)  # structured facts that need no model, e.g. ownership history
    people: list[Person] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)


# What kind of source each document kind is. The app groups sources this way, and extraction treats a conversation
# (a ticket or a chat) differently from a page someone keeps up to date.
FAMILY: dict[str, str] = {
    "handbook": "docs",
    "doc": "docs",
    "team_page": "docs",
    "wiki": "docs",
    "release": "docs",
    "notion": "docs",
    "confluence": "docs",
    "rfc": "decisions",
    "adr": "decisions",
    "ownership_map": "code_owners",
    "issue": "tickets",
    "pull": "tickets",
    "forum": "chats",
    "discussion": "chats",
    "thread": "chats",
    "slack": "chats",
}
CONVERSATIONS = tuple(k for k, f in FAMILY.items() if f in ("tickets", "chats"))


def family(kind: str | None) -> str:
    return FAMILY.get(kind or "", "docs")


ENTITY_LABELS = {"area": "Area", "team": "Team", "person": "Person", "topic": "Topic"}
ENTITY_KEYS = {"Area": "slug", "Team": "slug", "Person": "handle", "Topic": "key"}


def entity(key: str) -> tuple[str, str, str] | None:
    """`"area:notebooks"` -> `("Area", "slug", "notebooks")`. None for a plain phrase."""
    prefix, sep, rest = key.partition(":")
    label = ENTITY_LABELS.get(prefix)
    if not sep or not label or not rest:
        return None
    return label, ENTITY_KEYS[label], rest
