"""People across sources: one person, whichever tool they wrote in.

A person a connector meets is keyed by their email when the source shares it, so the same person in Slack, Linear
and Jira is one `(:Person)`. The email itself is never stored: the handle is `id:<hash>`, a one-way hash of the
lowercased address, used only to match. Without an email the handle is the source's own id (`slack:u024be7lh`),
and the source id is kept on the person too (`slack_id`, `notion_id` ...), so a later sync that does see the email
still knows who it is.
"""

import hashlib
from dataclasses import dataclass, field

from canon.sources.connector import Result
from canon.types import Person


def email_key(email: str | None) -> str | None:
    """`id:<16 hex>` for an email, or None. One-way: the email cannot be read back from it."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    return "id:" + hashlib.sha256(f"canon-person:{email}".encode()).hexdigest()[:16]


@dataclass
class People:
    """The people one connector met, by their source id."""

    source: str  # "slack", "notion" ...
    by_id: dict[str, Person] = field(default_factory=dict)
    props: dict[str, dict[str, str]] = field(default_factory=dict)  # handle -> {"slack_id": ...}

    def add(self, source_id: str | None, name: str | None, email: str | None = None) -> str | None:
        """The handle for a person, recorded once. None without an id."""
        if not source_id:
            return None
        known = self.by_id.get(source_id)
        if known is not None:
            if name and name.strip() and known.name == self.placeholder:
                self.by_id[source_id] = Person(known.handle, name.strip())
            return known.handle
        handle = email_key(email) or f"{self.source}:{source_id}".lower()
        self.by_id[source_id] = Person(handle, (name or "").strip() or self.placeholder)
        self.props.setdefault(handle, {})[f"{self.source}_id"] = source_id
        return handle

    @property
    def placeholder(self) -> str:
        return f"{self.source.title()} user"

    def get(self, source_id: str | None) -> str | None:
        p = self.by_id.get(source_id or "")
        return p.handle if p else None

    def name(self, source_id: str | None) -> str | None:
        p = self.by_id.get(source_id or "")
        return p.name if p else None

    @property
    def people(self) -> list[Person]:
        return list({p.handle: p for p in self.by_id.values()}.values())


@dataclass
class SourceResult(Result):
    """A connector's result, plus what the shared pipeline writes onto people (their source ids) and the documents
    the source says are gone."""

    people_props: dict[str, dict[str, str]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)  # document ids deleted or archived at the source
