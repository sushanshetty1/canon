"""Ownership history to dated, windowed `owned_by` facts, for any source that records who owns what in a file
kept in git: PostHog's ownership map, a repository's CODEOWNERS.

The caller walks the file's versions oldest first and hands over, for each version that changed something, its date,
the passage that states the change, and every area's owner list at that version. An area whose owner list changed
starts a new window for every owner in its new list, stated in that version. A co-owner that stays is restated
alongside the one that joins, so the two read as co-owners from one source, not as one replacing the other. A window
closes the day its area's owner list changes; an area that leaves the file closes all its windows.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from canon.sources.text import fact_id
from canon.types import Fact


@dataclass(frozen=True)
class Window:
    area: str
    owner: str
    start: str
    end: str | None
    passage_id: str


def owner_windows(versions: Iterable[tuple[str, str, dict[str, tuple[str, ...]]]]) -> list[Window]:
    """`versions` is `(day, passage_id, {area: owners})` per version, oldest first."""
    previous: dict[str, tuple[str, ...]] = {}
    open_windows: dict[tuple[str, str], tuple[str, str]] = {}  # (area, owner) -> (start, passage id)
    closed: list[Window] = []
    for day, passage_id, current in versions:
        changed = {a for a in set(previous) | set(current) if previous.get(a, ()) != current.get(a, ())}
        for pair in sorted(p for p in open_windows if p[0] in changed):
            start, pid = open_windows.pop(pair)
            if start != day:  # a window that opened and closed on one day never held
                closed.append(Window(*pair, start, day, pid))
        for area in sorted(changed & set(current)):
            for owner in current[area]:
                open_windows[(area, owner)] = (day, passage_id)
        previous = dict(current)
    windows = closed + [Window(a, o, s, None, p) for (a, o), (s, p) in open_windows.items()]
    return sorted(windows, key=lambda w: (w.area, w.start, w.owner))


def owned_by_facts(
    windows: Iterable[Window],
    *,
    value: Callable[[str], str],
    text: Callable[[Window], str],
    authority: int = 3,
) -> list[Fact]:
    """One `owned_by` fact per window. `value(owner)` is the entity key, `text(window)` the sentence."""
    facts = []
    for w in windows:
        subject, val = f"area:{w.area}", value(w.owner)
        facts.append(
            Fact(
                id=fact_id(subject, "owned_by", val, w.passage_id),
                subject=subject,
                predicate="owned_by",
                value=val,
                text=text(w),
                valid_from=w.start,
                passage_id=w.passage_id,
                authority=authority,
                valid_to=w.end,
            )
        )
    return facts
