"""Text helpers every connector shares: Markdown and MDX to plain text, passages with stable ids, fact ids.

A passage id is addressed by its content, so a passage whose text changes gets a new id. The writer then detaches
the old passage (its facts can be closed) instead of rewriting it in place, and extraction only ever runs on text it
has not seen.
"""

import hashlib
import re

from canon.types import Passage


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def day(iso: str | None) -> str:
    """The date part of an ISO timestamp."""
    return (iso or "")[:10]


_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Simple `key: value` frontmatter, and the body after it."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, text[m.end() :]


def clean_mdx(body: str, team_names: dict[str, str] | None = None) -> str:
    """MDX to plain Markdown. The components that name a team or a person become their names; the rest go."""

    team_names = team_names or {}

    def small_team(m: re.Match) -> str:
        slug = m.group(1)
        return f"{team_names.get(slug, slug.replace('-', ' ').title())} team"

    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"^\s*(import|export)\s.*$", "", body, flags=re.M)
    body = re.sub(r"```.*?```", "", body, flags=re.S)  # code is not knowledge about the company
    body = re.sub(r"<SmallTeam\s+slug=[\"']([^\"']+)[\"'][^>]*/>", small_team, body)
    body = re.sub(r"<TeamMember\s+name=[\"']([^\"']+)[\"'][^>]*/>", r"\1", body)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)  # images
    body = re.sub(r"<[A-Za-z][\w.]*(\s[^<>]*?)?/>", "", body, flags=re.S)  # other self-closing components
    body = re.sub(r"</?[A-Za-z][\w.]*(\s[^<>]*?)?>", "", body, flags=re.S)  # tags around text: keep the text
    body = re.sub(r"[ \t]+\n", "\n", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_passages(body: str, *, max_chars: int = 900) -> list[str]:
    """Split by heading, then by paragraph, into chunks of at most about `max_chars`.

    Each chunk starts with its section heading, so a passage read alone still says what it is about.
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        m = _HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)

    passages: list[str] = []
    for heading, lines in sections:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(lines)) if p.strip()]
        pieces: list[str] = []
        for p in paragraphs:
            if len(p) <= max_chars:
                pieces.append(p)
                continue
            # A long paragraph (often a list or a table) is split on lines, and a long line on sentences.
            units: list[str] = []
            for line in p.splitlines():
                units += [line] if len(line) <= max_chars else _SENTENCE.split(line)
            current = ""
            for u in units:
                if current and len(current) + len(u) + 1 > max_chars:
                    pieces.append(current)
                    current = u
                else:
                    current = f"{current}\n{u}" if current else u
            if current:
                pieces.append(current)
        chunk = ""
        for piece in pieces:
            if chunk and len(chunk) + len(piece) + 2 > max_chars:
                passages.append(f"{heading}\n{chunk}" if heading else chunk)
                chunk = piece
            else:
                chunk = f"{chunk}\n\n{piece}" if chunk else piece
        if chunk:
            passages.append(f"{heading}\n{chunk}" if heading else chunk)
    return passages


def passages_of(doc_id: str, texts: list[str]) -> list[Passage]:
    """Passages with content-addressed ids, `doc#<sha1(text)[:10]>`.

    A passage whose text changes gets a new id, so the writer detaches the old one (and the facts it carried can
    be closed) instead of rewriting its text in place. Repeated text within one document is kept once.
    """
    seen: dict[str, Passage] = {}
    for text in texts:
        pid = f"{doc_id}#{hashlib.sha1(text.encode()).hexdigest()[:10]}"
        seen.setdefault(pid, Passage(pid, doc_id, text))
    return list(seen.values())


def fact_id(subject: str, predicate: str, value: str, passage_id: str) -> str:
    """A fact's id: the same statement from the same passage always gets the same id."""
    return hashlib.sha1(f"{subject}|{predicate}|{value}|{passage_id}".encode()).hexdigest()[:16]
