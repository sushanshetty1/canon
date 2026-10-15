"""The fix queue: out-of-date lines on a company's pages, each drafted as a checked correction, routed to the people
who own it, and filed as a GitHub issue once a person approves.

- `build(graph)` opens, resolves and routes fixes: graph work only (`canon.fixes.queue`).
- `draft(graph, model=..., entail=...)` writes and checks each correction (`canon.fixes.draft`).
- `approve` and `dismiss` are the two things a person does with a fix.
- `canon.fixes.issues` turns a fix into an issue and files it (dry run by default).
"""

from canon.fixes.draft import draft
from canon.fixes.queue import STATUSES, TransitionError, approve, build, dismiss, get_fix, list_fixes, totals

__all__ = ["STATUSES", "TransitionError", "approve", "build", "dismiss", "draft", "get_fix", "list_fixes", "totals"]

