"""What every source of company knowledge looks like to Canon, so a workspace can read many of them.

A connector reads one place a company keeps knowledge (a GitHub repository, a Slack workspace, a Notion workspace,
Linear, Jira, Confluence, an uploaded export) and returns a `Batch`: documents with passages, people, teams, areas,
activity and any structured facts it can state without a model (an owner field, an assignee, a status). The shared
pipeline then writes the batch, extracts facts from the passages worth reading, links what replaced what, judges
disputes and refreshes people, decisions and fixes, whatever the source.

A workspace's connections live in its own graph:

    (:Connection {id, kind, label, config, secret, status, last_synced_at, cursor, error})

`config` is JSON the connector needs (a site URL, channel ids); `secret` is the sealed credential
(`canon.cloud.crypto`), never returned by the API. `cursor` is the connector's own note of where it stopped, so a sync
reads only what changed.

Document ids are prefixed by the connector kind (`slack:`, `notion:`, `linear:` ...), and document kinds say what the
knowledge is, so answers can say where a sentence came from:

| Kind group | Document kinds |
| --- | --- |
| docs | handbook, team_page, doc, wiki, notion_page, confluence_page, upload |
| tickets | issue, pull, linear_issue, jira_issue |
| chats | forum, discussion, comment_thread, slack_thread |
| decisions | rfc, adr, release |
| structure | ownership_map, roster |
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from canon.types import Batch

Report = Callable[..., None]  # report(step="...", done=n, total=m): progress for the workspace's job

KIND_GROUPS = {
    "docs": ("handbook", "team_page", "doc", "wiki", "notion_page", "confluence_page", "upload"),
    "tickets": ("issue", "pull", "linear_issue", "jira_issue"),
    "chats": ("forum", "discussion", "comment_thread", "slack_thread"),
    "decisions": ("rfc", "adr", "release"),
    "structure": ("ownership_map", "roster"),
}


def group_of(kind: str) -> str:
    return next((g for g, kinds in KIND_GROUPS.items() if kind in kinds), "docs")


@dataclass
class Result:
    batch: Batch
    cursor: str | None = None  # where the next sync starts
    notes: list[str] = field(default_factory=list)  # anything a person should know (a channel it could not read)


class Connector(Protocol):
    kind: str  # "github", "slack", "notion", "linear", "jira", "confluence", "upload"
    label: str  # what the app calls it: "Slack", "Notion"

    def read(self, *, cursor: str | None, report: Report) -> Result: ...
