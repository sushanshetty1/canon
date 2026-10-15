"""Notion, through an internal integration token: the pages and databases shared with the integration.

- **Pages.** `POST /v1/search` lists the pages shared with the integration, most recently edited first. Each page's
  blocks are read into text (`/v1/blocks/{id}/children`, nested blocks to `max_depth`): headings, paragraphs, lists,
  to-dos, toggles, quotes, callouts and tables. Code blocks are skipped. Each page is a `notion_page` dated by its
  `last_edited_time`.
- **Database rows** are pages too. Each row is a small `notion_page` of its properties (`Owner: Ana`, `Status: In
  progress`) and its body. A row with an owner-like people property (Owner, Assignee, Lead, DRI) and a status says
  who owns it, so it becomes an area with an `owned_by` fact (authority 2) for each owner, with no model involved.
- **People.** A page's `created_by` and `last_edited_by` become people and authors. Names come from `/v1/users`
  when the integration may read user information; emails, when shared, are only hashed for matching.

Incremental: the cursor is the newest `last_edited_time` read. Search is sorted by it, so a sync stops at the first
page not edited since (Notion rounds the time to the minute, so pages edited in that minute are read again, which
writes nothing new). Bounded by `max_pages` per sync and `max_blocks` per page.
"""

import re
import time
from collections.abc import Callable

from canon.sources.client import Client, SourceError, capped
from canon.sources.connector import Report
from canon.sources.identity import People, SourceResult
from canon.sources.text import day, fact_id, passages_of, slugify, split_passages
from canon.types import Activity, Area, Batch, Doc, Fact

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
OWNER_PROP = re.compile(r"\b(owner|owners|owned by|assignee|assignees|assigned to|lead|dri|responsible)\b", re.I)
STATUS_PROP = re.compile(r"\b(status|state|stage)\b", re.I)
TEXT_BLOCKS = {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "to_do",
               "toggle", "quote", "callout"}
CONTAINERS = {"column_list", "column", "synced_block", "table"}


def plain(rich: list | None) -> str:
    return "".join((r or {}).get("plain_text") or "" for r in rich or []).strip()


class NotionConnector:
    kind = "notion"
    label = "Notion"

    def __init__(self, token: str, config: dict | None = None, *, http: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config or {}
        self.client = Client("Notion", http=http, sleep=sleep,
                             headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION})
        self.max_pages = capped(self.config, "max_pages", 300, 2000)
        self.max_blocks = capped(self.config, "max_blocks", 400, 2000)
        self.max_depth = capped(self.config, "max_depth", 3, 5)
        self.people = People("notion")
        self._users: dict[str, dict | None] = {}
        self._databases: dict[str, str] = {}

    def check(self) -> dict:
        me = self.client.json("GET", f"{API}/users/me")
        bot = me.get("bot") or {}
        return {"workspace": bot.get("workspace_name") or ""}

    # ----- people

    def person(self, ref: dict | None) -> str | None:
        """A user reference (`{"object": "user", "id": ...}`, maybe with name and email) to a handle."""
        if not ref or ref.get("object") != "user" or not ref.get("id"):
            return None
        uid = ref["id"]
        info = ref if ref.get("name") else self._user(uid)
        if info is None or info.get("type") == "bot":
            return None
        email = (info.get("person") or {}).get("email")
        return self.people.add(uid, info.get("name"), email) if info.get("name") else None

    def _user(self, uid: str) -> dict | None:
        if uid not in self._users:
            info = None
            if len(self._users) < 1000:
                try:
                    info = self.client.json("GET", f"{API}/users/{uid}")
                except SourceError as e:
                    if e.status == 429:
                        raise
            self._users[uid] = info
        return self._users[uid]

    # ----- pages

    def _search(self, since: str | None, notes: list[str]) -> list[dict]:
        pages: list[dict] = []
        start = None
        while True:
            body = {"filter": {"property": "object", "value": "page"}, "page_size": 100,
                    "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
            if start:
                body["start_cursor"] = start
            res = self.client.json("POST", f"{API}/search", json=body)
            for page in res.get("results") or []:
                if since and (page.get("last_edited_time") or "") < since:
                    return pages
                pages.append(page)
                if len(pages) >= self.max_pages:
                    if res.get("has_more") or page is not (res.get("results") or [])[-1]:
                        notes.append(f"Read the {self.max_pages} most recently edited pages (max_pages).")
                    return pages
            start = res.get("next_cursor")
            if not res.get("has_more") or not start:
                return pages

    def _blocks(self, block_id: str, depth: int, budget: list[int]) -> list[str]:
        lines: list[str] = []
        start = None
        while budget[0] > 0:
            params = {"page_size": 100}
            if start:
                params["start_cursor"] = start
            try:
                res = self.client.json("GET", f"{API}/blocks/{block_id}/children", params=params)
            except SourceError as e:
                if e.status == 429:
                    raise
                return lines
            for block in res.get("results") or []:
                budget[0] -= 1
                kind = block.get("type") or ""
                data = block.get(kind) or {}
                if kind in TEXT_BLOCKS:
                    text = plain(data.get("rich_text"))
                    if kind.startswith("heading_"):
                        lines.append("\n" + "#" * int(kind[-1]) + " " + text + "\n" if text else "")
                    elif kind in ("bulleted_list_item", "numbered_list_item", "toggle"):
                        lines.append(f"- {text}" if text else "")
                    elif kind == "to_do":
                        lines.append(f"- [{'x' if data.get('checked') else ' '}] {text}" if text else "")
                    elif text:
                        lines.append(f"\n{text}\n")
                elif kind == "table_row":
                    cells = [plain(c) for c in data.get("cells") or []]
                    if any(cells):
                        lines.append(" | ".join(cells))
                if block.get("has_children") and depth < self.max_depth and (kind in TEXT_BLOCKS or kind in CONTAINERS):
                    lines += self._blocks(block["id"], depth + 1, budget)
                if budget[0] <= 0:
                    break
            start = res.get("next_cursor")
            if not res.get("has_more") or not start:
                break
        return lines

    def _database(self, db_id: str) -> str:
        if db_id not in self._databases:
            name = "Database"
            try:
                name = plain(self.client.json("GET", f"{API}/databases/{db_id}").get("title")) or name
            except SourceError as e:
                if e.status == 429:
                    raise
            self._databases[db_id] = name
        return self._databases[db_id]

    def _property(self, prop: dict) -> tuple[str, list[str]]:
        """A property's value as text, and the handles of the people it names."""
        kind = prop.get("type")
        value = prop.get(kind)
        if kind in ("title", "rich_text"):
            return plain(value), []
        if kind in ("select", "status"):
            return (value or {}).get("name") or "", []
        if kind == "multi_select":
            return ", ".join(o.get("name") or "" for o in value or []), []
        if kind in ("people", "created_by", "last_edited_by"):
            refs = value if isinstance(value, list) else [value]
            handles = [h for h in (self.person(r) for r in refs) if h]
            names = [self.people.name(r.get("id")) for r in refs if r and self.people.get(r.get("id"))]
            return ", ".join(n for n in names if n), handles
        if kind == "date" and value:
            return (value.get("start") or "") + (f" to {value['end']}" if value.get("end") else ""), []
        if kind == "number" and value is not None:
            return str(value), []
        if kind == "checkbox":
            return "Yes" if value else "No", []
        if kind == "url":
            return value or "", []
        if kind == "formula" and value:
            v = value.get(value.get("type") or "")
            return "" if v is None or isinstance(v, dict) else str(v), []
        return "", []  # emails, phone numbers, files and relations are not read

    def read(self, *, cursor: str | None, report: Report) -> SourceResult:
        notes: list[str] = []
        report(step="read_notion", done=0, total=1)
        pages = self._search(cursor, notes)
        batch = Batch()
        newest = cursor
        for i, page in enumerate(pages):
            report(step="read_notion", done=i, total=len(pages))
            edited = page.get("last_edited_time") or ""
            if not newest or edited > newest:
                newest = edited
            if page.get("archived") or page.get("in_trash"):
                continue
            self._page(batch, page)
        report(step="read_notion", done=len(pages), total=len(pages))
        batch.people = self.people.people
        batch.activity = list(dict.fromkeys(batch.activity))
        return SourceResult(batch=batch, cursor=newest, notes=notes, people_props=self.people.props)

    def _page(self, batch: Batch, page: dict) -> None:
        pid = page["id"]
        doc_id = f"notion:{pid.replace('-', '')}"
        props = page.get("properties") or {}
        title = next((plain(p.get("title")) for p in props.values() if p.get("type") == "title"), "") or "Untitled"
        parent = page.get("parent") or {}
        in_db = parent.get("type") == "database_id"
        edited = day(page.get("last_edited_time"))
        creator = self.person(page.get("created_by"))
        editor = self.person(page.get("last_edited_by"))
        texts: list[str] = []
        owners: list[str] = []
        status = ""
        if in_db:
            db = self._database(parent.get("database_id") or "")
            lines = [f"{db}: {title}"]
            for name, prop in props.items():
                if prop.get("type") == "title":
                    continue
                text, handles = self._property(prop)
                if text:
                    lines.append(f"{name}: {text}")
                if prop.get("type") == "people" and OWNER_PROP.search(name):
                    owners += handles
                if not status and (prop.get("type") == "status" or (prop.get("type") == "select" and STATUS_PROP.search(name))):
                    status = text
            texts.append("\n".join(lines))
            title = f"{db}: {title}"
        body = "\n".join(self._blocks(pid, 1, [self.max_blocks]))
        texts += split_passages(body if in_db or not body else f"# {title}\n{body}")
        passages = passages_of(doc_id, [t for t in texts if t.strip()])
        if not passages:
            return
        batch.docs.append(Doc(doc_id, "notion_page", title, page.get("url") or "", edited, author=creator))  # type: ignore[arg-type]
        batch.passages += passages
        if creator:
            batch.activity.append(Activity(creator, doc_id, "AUTHORED", day(page.get("created_time"))))
        if editor:
            batch.activity.append(Activity(editor, doc_id, "AUTHORED", edited))
        if in_db and owners and status:
            name = title.split(": ", 1)[-1]
            slug = slugify(name)[:60]
            if slug:
                batch.areas.append(Area(slug, name))
                subject = f"area:{slug}"
                for handle in dict.fromkeys(owners):
                    who = next((p.name for p in self.people.by_id.values() if p.handle == handle), handle)
                    value = f"person:{handle}"
                    batch.facts.append(Fact(
                        id=fact_id(subject, "owned_by", value, passages[0].id), subject=subject, predicate="owned_by",
                        value=value, text=f"{name} is owned by {who} (status: {status}).", valid_from=edited,
                        passage_id=passages[0].id, authority=2,
                    ))
