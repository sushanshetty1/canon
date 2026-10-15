"""The closed predicate vocabulary, source authority, and topic keys.

Supersession compares facts that share a subject and a predicate, so both must be stable: the predicate comes from
this short list and nothing else, and a topic named in different words on different pages should land on one key.
Authority says which source wins when two disagree: the ownership map outranks a team page, which outranks the
handbook, which outranks a ticket or a chat: an issue, a comment thread, a discussion, a forum or Slack thread.
"""

import re

from canon.types import Kind

PREDICATES: dict[str, str] = {
    "owned_by": "an area is owned by a team (subject area:..., value team:...)",
    "member_of": "a person is a member of a team (subject person:..., value team:...)",
    "leads": "a person leads a team (subject person:..., value team:...)",
    "decided": "a decision was made about a topic (subject topic:..., value a short decision phrase)",
    "process": "how something is done (subject topic:..., value a short description of the process)",
    "policy": "a rule people must follow (subject topic:..., value the rule)",
    "uses": "a team or topic uses a tool (subject team:... or topic:..., value the tool)",
    "contact_for": "who to ask about a topic or area (subject topic:... or area:..., value person:... or team:...)",
}

# Subjects and values each predicate allows, by key prefix. "phrase" is a short plain phrase.
SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "owned_by": (("area",), ("team",)),
    "member_of": (("person",), ("team",)),
    "leads": (("person",), ("team",)),
    "decided": (("topic", "area", "team"), ("phrase",)),
    "process": (("topic", "area", "team"), ("phrase",)),
    "policy": (("topic", "area", "team"), ("phrase",)),
    "uses": (("team", "topic", "area"), ("phrase",)),
    "contact_for": (("topic", "area"), ("person", "team")),
}

AUTHORITY: dict[Kind, int] = {
    "ownership_map": 3,
    "team_page": 2,
    "rfc": 2,
    "adr": 2,  # a decision record in a repository, like an RFC
    "handbook": 1,
    "doc": 1,  # a Markdown page in a repository
    "wiki": 1,
    "release": 1,
    "notion": 1,
    "confluence": 1,
    "pull": 1,
    # Tickets and chats: what someone said in a conversation ranks below any page.
    "issue": 0,
    "forum": 0,
    "discussion": 0,
    "thread": 0,
    "slack": 0,
}

STOPWORDS = frozenset(
    """a an and are as at be by for from how in into is it its of on or our over per so that the their this to
    up via we what when where which who why with your you""".split()
)

MAX_TOPIC_WORDS = 4


def topic_words(text: str) -> list[str]:
    """The content words of a topic: lowercase, no stopwords, in order, without repeats."""
    words = re.findall(r"[a-z0-9]+", text.lower().removeprefix("topic:"))
    seen: list[str] = []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen


def normalise_topic(text: str) -> str | None:
    """`"topic:The Friday deploys"` -> `"topic:friday-deploys"`. None when nothing is left."""
    words = topic_words(text)[:MAX_TOPIC_WORDS]
    return f"topic:{'-'.join(words)}" if words else None


def _stem(word: str) -> str:
    """A light plural fold, so `deploy` and `deploys` count as one word when topics are compared."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def merge_topics(keys: list[str]) -> dict[str, str]:
    """Map each topic key to one representative, merging keys whose slugs share all content words.

    `topic:friday-deploys` and `topic:deploy-friday` share all their words (plurals folded) and merge. A key whose words are a
    subset of another's (`topic:deploys` and `topic:friday-deploys`) is not merged: one is broader than the other.
    A cheap union-find over the word sets.
    """
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    by_words: dict[frozenset[str], str] = {}
    for key in sorted(set(keys)):
        parent[key] = key
        words = frozenset(_stem(w) for w in topic_words(key))
        if words in by_words:
            a, b = find(by_words[words]), find(key)
            if a != b:
                parent[max(a, b)] = min(a, b)  # deterministic: the alphabetically first key wins
        else:
            by_words[words] = key
    return {k: find(k) for k in parent}
