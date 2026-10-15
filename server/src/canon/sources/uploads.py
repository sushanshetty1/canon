"""Chats and docs from outside GitHub, uploaded as an export: a Slack export, or a Notion or Confluence export.

Both arrive as one zip. It is read in memory, never unpacked to disk, and read carefully: a size limit on the upload,
on every file and on everything inside together, a cap on how many files there are and on how far a file may
compress, so a small zip that unpacks to gigabytes is refused before it is read. Only the files a parser wants
(`.json` from Slack, `.md` and `.html` from Notion and Confluence) are read at all.

- **Slack** (`channels.json`, `users.json`, `<channel>/<date>.json`). Messages are grouped into threads: a reply
  belongs to its thread, and messages outside any thread that follow each other within half an hour are one
  conversation. Each thread is a document (kind `slack`), with a passage per run of messages from one person on
  one day, saying who said it (their Slack display name) and when. People appear as `name:<slug>`, since a Slack
  member has no GitHub handle. Channels only: direct messages and private groups in an export are left out.
- **Notion or Confluence** (Markdown or HTML pages). Each page is a document (kind `notion` or `confluence`) dated by
  the date it carries ("Last edited time", "last modified on"), or by the day it was read when it carries none.

`parse(kind, data)` returns a `Batch`; `canon.ingest.ingest_upload` writes it and extracts facts like any source.
"""

import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath

from canon.sources.text import Turn, clean_mdx, day, frontmatter, passages_of, slugify, split_passages, turn_passages
from canon.types import Activity, Batch, Doc, Person

KINDS = ("slack", "pages")

MAX_UPLOAD = 50 * 1024 * 1024  # bytes sent
MAX_FILE = 20 * 1024 * 1024  # one file inside, unpacked
MAX_TOTAL = 250 * 1024 * 1024  # everything read, unpacked
MAX_FILES = 20_000  # entries in the archive
MAX_RATIO = 150  # how far a file may have been compressed
MAX_THREADS = 3000  # Slack threads kept, newest first
MAX_PAGES = 2000
GAP_SECONDS = 30 * 60  # messages outside a thread this close together are one conversation


class UploadError(ValueError):
    """The upload cannot be read. The message is safe to show."""


# ----- reading a zip safely --------------------------------------------------------------------------------------


@dataclass
class _Budget:
    files: int = 0
    total: int = 0


def read_zip(data: bytes, suffixes: tuple[str, ...], *, budget: _Budget | None = None, depth: int = 0) -> dict[str, bytes]:
    """The files in a zip whose names end in `suffixes`, by their path inside. A zip inside the zip (Notion splits
    big exports into parts) is read once more, within the same limits."""
    if len(data) > MAX_UPLOAD:
        raise UploadError("The export is larger than 50 MB.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise UploadError("This is not a zip file.") from None
    budget = budget or _Budget()
    out: dict[str, bytes] = {}
    with archive:
        for info in archive.infolist():
            budget.files += 1
            if budget.files > MAX_FILES:
                raise UploadError("The export holds too many files.")
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or parts[:1] == ("__MACOSX",) or parts[-1].startswith("."):
                continue
            nested = name.lower().endswith(".zip") and depth == 0
            if not nested and not name.lower().endswith(suffixes):
                continue
            if info.flag_bits & 0x1:
                raise UploadError("The export is encrypted.")
            if info.file_size > MAX_FILE and not nested:
                raise UploadError("A file in the export is larger than 20 MB.")
            if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise UploadError("The export unpacks to far more than its size. It was not read.")
            if budget.total + info.file_size > MAX_TOTAL:
                raise UploadError("The export unpacks to more than 250 MB.")
            limit = MAX_UPLOAD if nested else MAX_FILE
            with archive.open(info) as f:
                blob = f.read(limit + 1)  # the size in the header can lie: never read past the limit
            if len(blob) > limit:
                raise UploadError("A file in the export is larger than it says.")
            if nested:
                out.update({f"{name}/{k}": v for k, v in read_zip(blob, suffixes, budget=budget, depth=1).items()})
                continue
            budget.total += len(blob)
            if budget.total > MAX_TOTAL:
                raise UploadError("The export unpacks to more than 250 MB.")
            out[name] = blob
    return out


def _json(blob: bytes):
    try:
        return json.loads(blob.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


# ----- Slack -----------------------------------------------------------------------------------------------------

_SKIP_SUBTYPES = {
    "channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name", "channel_archive",
    "channel_unarchive", "pinned_item", "unpinned_item", "bot_message", "bot_add", "bot_remove", "tombstone",
    "group_join", "group_leave", "reminder_add",
}


def _iso(ts: str | float | None) -> str:
    try:
        return datetime.fromtimestamp(float(ts or 0), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return ""


def _display(user: dict) -> str:
    profile = user.get("profile") or {}
    return (
        (profile.get("display_name") or "").strip()
        or (profile.get("real_name") or "").strip()
        or (user.get("real_name") or "").strip()
        or (user.get("name") or "").strip()
    )


def slack_text(text: str, names: dict[str, str], channels: dict[str, str]) -> str:
    """Slack's markup as plain words: mentions by display name, channels by name, links by their label."""
    text = re.sub(r"<@([UW][A-Z0-9]+)(?:\|([^>]+))?>", lambda m: "@" + (names.get(m.group(1)) or m.group(2) or "someone"), text)
    text = re.sub(r"<#([CG][A-Z0-9]+)(?:\|([^>]*))?>", lambda m: "#" + (m.group(2) or channels.get(m.group(1)) or "channel"), text)
    text = re.sub(r"<!(here|channel|everyone)(?:\|[^>]*)?>", r"@\1", text)
    text = re.sub(r"<!subteam\^[A-Z0-9]+(?:\|([^>]+))?>", lambda m: m.group(1) or "@group", text)
    text = re.sub(r"<(?:https?|mailto):[^|>]+\|([^>]+)>", r"\1", text)
    text = re.sub(r"<((?:https?):[^>]+)>", r"\1", text)
    return html.unescape(text).strip()


@dataclass
class _Thread:
    channel: str
    key: str
    messages: list[dict] = field(default_factory=list)


def parse_slack(files: dict[str, bytes], *, max_threads: int = MAX_THREADS) -> Batch:
    """A Slack export as threads. Raises UploadError when it is not one."""
    found = sorted((n for n in files if PurePosixPath(n).name == "channels.json"), key=lambda n: (n.count("/"), n))
    if not found:
        raise UploadError("This zip has no channels.json, so it is not a Slack export.")
    base = str(PurePosixPath(found[0]).parent)
    prefix = "" if base == "." else f"{base}/"
    channel_rows = _json(files.get(f"{prefix}channels.json", b"[]")) or []
    user_rows = _json(files.get(f"{prefix}users.json", b"[]")) or []
    if not isinstance(channel_rows, list):
        raise UploadError("channels.json is not a list of channels.")
    names = {u["id"]: _display(u) for u in user_rows if isinstance(u, dict) and u.get("id") and _display(u)}
    bots = {u["id"] for u in user_rows if isinstance(u, dict) and (u.get("is_bot") or u.get("id") == "USLACKBOT")}
    channels = {c["id"]: c["name"] for c in channel_rows if isinstance(c, dict) and c.get("id") and c.get("name")}

    threads: dict[tuple[str, str], _Thread] = {}
    for channel in sorted(set(channels.values())):
        days = sorted(n for n in files if n.startswith(f"{prefix}{channel}/") and n.endswith(".json"))
        loose: _Thread | None = None
        last_ts = 0.0
        seen: set[str] = set()
        for name in days:
            rows = _json(files[name])
            if not isinstance(rows, list):
                continue
            for m in sorted((r for r in rows if isinstance(r, dict)), key=lambda r: float(r.get("ts") or 0)):
                ts = str(m.get("ts") or "")
                if not ts or ts in seen or m.get("type", "message") != "message":
                    continue
                seen.add(ts)
                if m.get("subtype") in _SKIP_SUBTYPES or m.get("bot_id") or m.get("user") in bots:
                    continue
                if not (m.get("text") or "").strip():
                    continue
                parent = str(m.get("thread_ts") or "")
                if parent:
                    threads.setdefault((channel, parent), _Thread(channel, parent)).messages.append(m)
                    continue
                # Outside any thread: messages close together are one conversation.
                if loose is None or float(ts) - last_ts > GAP_SECONDS:
                    loose = threads.setdefault((channel, ts), _Thread(channel, ts))
                loose.messages.append(m)
                last_ts = float(ts)

    batch = Batch()
    people: dict[str, Person] = {}
    kept = sorted((t for t in threads.values() if t.messages), key=lambda t: -max(float(m["ts"]) for m in t.messages))
    for t in kept[:max_threads]:
        msgs = sorted(t.messages, key=lambda m: float(m["ts"]))
        turns = []
        for m in msgs:
            who = names.get(m.get("user") or "") or _display({"profile": m.get("user_profile") or {}}) or "Someone"
            handle = f"name:{slugify(who)}" if who != "Someone" and slugify(who) else None
            if handle:
                people.setdefault(handle, Person(handle, who))
            turns.append(Turn(who, _iso(m["ts"]), slack_text(m.get("text") or "", names, channels), handle))
        first = turns[0]
        snippet = " ".join(first.text.split())
        snippet = snippet if len(snippet) <= 70 else snippet[:67].rsplit(" ", 1)[0] + "..."
        doc = Doc(
            id=f"slack:{t.channel}/{t.key}",
            kind="slack",
            title=f"#{t.channel}: {snippet}",
            url="",
            updated_at=day(turns[-1].at),
            author=first.author,
        )
        passages = turn_passages(doc.id, turns, merge=True)
        if not passages:
            continue
        batch.docs.append(doc)
        batch.passages += passages
        for i, turn in enumerate(turns):
            if turn.author:
                batch.activity.append(Activity(turn.author, doc.id, "AUTHORED" if i == 0 else "COMMENTED", day(turn.at)))
    batch.people = sorted(people.values(), key=lambda p: p.handle)
    batch.activity = sorted(set(batch.activity), key=lambda a: (a.doc_id, a.handle, a.rel, a.at))
    return batch


# ----- Notion and Confluence -------------------------------------------------------------------------------------

_NOTION_ID = re.compile(r"\s*[0-9a-f]{32}$", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_WORD_DATE = r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})"
_ISO_DATE = r"(\d{4})-(\d{2})-(\d{2})"
# Which date a page says it was last changed, best first.
_DATE_LINES = (
    rf"last (?:edited|modified|updated)(?: time)?(?: by [^,\n]{{1,60}}?)?(?: on)?\s*[:@]?\s*@?(?:{_WORD_DATE}|{_ISO_DATE})",
    rf"(?:updated|modified|edited)(?: at| on)?\s*[:@]\s*@?(?:{_WORD_DATE}|{_ISO_DATE})",
    rf"created(?: time)?(?: by [^,\n]{{1,60}}?)?(?: on)?\s*[:@]?\s*@?(?:{_WORD_DATE}|{_ISO_DATE})",
    rf"\bdate\s*[:@]\s*@?(?:{_WORD_DATE}|{_ISO_DATE})",
)


def page_date(text: str) -> str | None:
    """The date a page says it was last changed (or made), as `YYYY-MM-DD`; None when it says none."""
    head = text[:3000]
    for pattern in _DATE_LINES:
        m = re.search(pattern, head, re.I)
        if not m:
            continue
        month, dd, yyyy, iy, im, idd = m.groups()
        try:
            if yyyy:
                value = date(int(yyyy), _MONTHS[month[:3].lower()], int(dd))
            else:
                value = date(int(iy), int(im), int(idd))
        except (KeyError, ValueError):
            continue
        return value.isoformat()
    return None


class _Text(HTMLParser):
    """HTML to plain Markdown-ish text: headings keep their level, list items their dash, the rest its words."""

    BLOCK = {"p", "div", "section", "article", "br", "tr", "table", "ul", "ol", "blockquote", "pre", "hr"}
    SKIP = {"script", "style", "head", "nav", "footer"}

    # Confluence's breadcrumbs and footer say nothing about the page.
    HIDDEN_IDS = {"breadcrumbs", "breadcrumb-section", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self._hidden: list[list] = []  # [tag, depth] of each hidden block we are inside

    def handle_starttag(self, tag, attrs):
        if self._hidden and tag == self._hidden[-1][0]:
            self._hidden[-1][1] += 1
        elif dict(attrs).get("id") in self.HIDDEN_IDS:
            self._hidden.append([tag, 1])
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if self.skip or self._hidden:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("td", "th"):
            self.out.append(" ")
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag):
        if self._hidden and tag == self._hidden[-1][0]:
            self._hidden[-1][1] -= 1
            if self._hidden[-1][1] == 0:
                self._hidden.pop()
            return
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self._in_title = False
        if not self.skip and not self._hidden and (re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK):
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self.skip and not self._hidden:
            self.out.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        body = "".join(self.out)
        body = re.sub(r"^\s*Document generated by Confluence.*$", "", body, flags=re.M | re.I)
        body = re.sub(r"[ \t]+\n", "\n", body)
        body = re.sub(r"\n[ \t]+", "\n", body)
        return re.sub(r"\n{3,}", "\n\n", body).strip()


def html_text(source: str) -> tuple[str, str]:
    """(title, text) of an HTML page."""
    parser = _Text()
    parser.feed(source)
    parser.close()
    return " ".join(parser.title.split()), parser.text()


def _page_title(path: str, meta: dict, body: str, html_title: str = "") -> str:
    if meta.get("title"):
        return meta["title"]
    m = re.search(r"^#\s+(.+?)\s*#*\s*$", body, re.M)
    if m:
        return re.sub(r"[*_`]", "", m.group(1)).strip()
    if html_title:
        return html_title.split(" : ", 1)[-1].strip()  # Confluence titles pages "Space : Page"
    stem = _NOTION_ID.sub("", PurePosixPath(path).stem)
    return stem.replace("_", " ").strip() or "Untitled page"


def parse_pages(files: dict[str, bytes], *, today: str | None = None) -> Batch:
    """A Notion or Confluence export as pages. Raises UploadError when there are none."""
    today = today or date.today().isoformat()
    pages = {n: b for n, b in files.items() if n.lower().endswith((".md", ".markdown", ".html", ".htm"))}
    if not pages:
        raise UploadError("This zip has no Markdown or HTML pages.")
    confluence = any(
        n.lower().endswith((".html", ".htm")) and (b"confluence" in b[:20000].lower() or b"page-metadata" in b[:20000])
        for n, b in list(pages.items())[:50]
    )
    batch = Batch()
    for path in sorted(pages)[:MAX_PAGES]:
        raw = pages[path].decode("utf-8", errors="replace")
        is_html = path.lower().endswith((".html", ".htm"))
        name = PurePosixPath(path).name.lower()
        if is_html and confluence and name == "index.html":
            continue  # the space's list of pages, not a page
        if is_html:
            html_title, text = html_text(raw)
            meta = {}
        else:
            html_title = ""
            meta, body = frontmatter(raw)
            text = clean_mdx(body)
        title = _page_title(path, meta, text, html_title)
        when = page_date(f"{json.dumps(meta)}\n{text}") or today
        kind = "confluence" if confluence else "notion"
        body = re.sub(rf"^\s*#\s+{re.escape(title)}\s*$", "", text, count=1, flags=re.M).strip()
        if not body:
            continue
        doc = Doc(f"{kind}:{path}", kind, title, "", when)  # type: ignore[arg-type]
        batch.docs.append(doc)
        batch.passages += passages_of(doc.id, [f"{title}\n{p}" if not p.startswith(title) else p for p in split_passages(body)])
    if not batch.docs:
        raise UploadError("The pages in this zip are empty.")
    return batch


def parse(kind: str, data: bytes) -> Batch:
    """An uploaded export as a batch. `kind` is "slack" or "pages" (Notion or Confluence)."""
    if kind == "slack":
        return parse_slack(read_zip(data, (".json",)))
    if kind == "pages":
        return parse_pages(read_zip(data, (".md", ".markdown", ".html", ".htm")))
    raise UploadError("Upload a Slack export, or a Notion or Confluence export.")
