"""Confluence Cloud, through an account email and an API token, with the v2 REST API.

- **Spaces** (`/wiki/api/v2/spaces`) become areas. `config["spaces"]` can narrow it to some space keys.
- **Pages** (`/wiki/api/v2/pages`, current pages, most recently changed first, with their storage-format body) become
  `confluence_page` documents dated by their latest version. The body's XHTML is read into text: headings, lists
  and tables are kept; code and macros' parameters are dropped. A page is about its space's area.
- **People.** The page owner authored it on the day it was made; the author of its latest version authored that
  version. Names come from `/wiki/api/v2/users-bulk`; emails, when shared, are only hashed for matching.

Incremental: the cursor is the newest version time read, and a sync stops at the first page whose latest version is
older. At most `max_pages` per sync and `max_page_chars` of text per page.
"""

import time
from collections.abc import Callable
from urllib.parse import urlparse

from canon.sources.atlassian import credentials, site_url
from canon.sources.client import Client, SourceError, capped
from canon.sources.connector import Report
from canon.sources.identity import People, SourceResult
from canon.sources.richtext import html_to_text
from canon.sources.text import day, passages_of, slugify, split_passages
from canon.types import Activity, Area, Batch, Doc


class ConfluenceConnector:
    kind = "confluence"
    label = "Confluence"

    def __init__(self, secret: dict, config: dict | None = None, *, http: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config or {}
        self.site = site_url(self.config.get("site"))
        email, token = credentials(secret.get("email"), secret.get("token"))
        self.client = Client("Confluence", http=http, sleep=sleep, auth=(email, token), headers={"Accept": "application/json"})
        self.max_pages = capped(self.config, "max_pages", 300, 2000)
        self.max_spaces = capped(self.config, "max_spaces", 50, 500)
        self.max_page_chars = capped(self.config, "max_page_chars", 200_000, 1_000_000)
        self.people = People("confluence")

    def _json(self, method: str, path: str, **kw):
        r = self.client.request(method, path if path.startswith("https://") else f"{self.site}{path}", **kw)
        if r.status_code == 401:
            raise SourceError("Confluence did not accept this email and API token.", status=401)
        if r.status_code == 403:
            raise SourceError("Confluence refused access. The account needs permission to view these spaces.", status=403)
        if r.status_code == 404:
            raise SourceError(f"There is no Confluence at {self.site.removeprefix('https://')}.", status=404)
        if r.status_code != 200:
            raise SourceError(f"Confluence answered with an error ({r.status_code}).", status=r.status_code)
        return r.json()

    def _next(self, body: dict) -> str | None:
        """The next page's path. Only a path on this site is followed."""
        nxt = (body.get("_links") or {}).get("next")
        if not nxt:
            return None
        parsed = urlparse(nxt)
        if parsed.scheme or parsed.netloc:
            return None
        return nxt if nxt.startswith("/wiki/") else "/wiki" + nxt

    def check(self) -> dict:
        me = self._json("GET", "/wiki/rest/api/user/current")
        if me.get("type") == "anonymous" or not me.get("accountId"):
            raise SourceError("Confluence did not accept this email and API token.", status=401)
        return {"account": me.get("displayName") or me.get("publicName") or ""}

    def _names(self, ids: list[str]) -> None:
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            try:
                body = self._json("POST", "/wiki/api/v2/users-bulk", json={"accountIds": chunk})
            except SourceError as e:
                if e.status == 429:
                    raise
                body = {}
            found = {u.get("accountId"): u for u in body.get("results") or []}
            for account in chunk:
                u = found.get(account) or {}
                if u.get("accountType") == "app":
                    continue
                self.people.add(account, u.get("displayName") or u.get("publicName"), u.get("email"))

    def read(self, *, cursor: str | None, report: Report) -> SourceResult:
        notes: list[str] = []
        batch = Batch()
        report(step="read_confluence", done=0, total=2)
        self.check()
        wanted = {str(k).strip().upper() for k in self.config.get("spaces") or [] if str(k).strip()}
        spaces: dict[str, tuple[str, str]] = {}  # space id -> (area slug, name)
        path: str | None = "/wiki/api/v2/spaces?limit=50"
        while path and len(spaces) < self.max_spaces:
            body = self._json("GET", path)
            for s in body.get("results") or []:
                if wanted and (s.get("key") or "").upper() not in wanted:
                    continue
                if len(spaces) >= self.max_spaces:
                    break
                name = s.get("name") or s.get("key") or "Space"
                slug = slugify(name)[:60] or str(s.get("id"))
                spaces[str(s.get("id"))] = (slug, name)
                batch.areas.append(Area(slug, name))
            path = self._next(body)
        report(step="read_confluence", done=1, total=2)

        pages: list[dict] = []
        query = "limit=50&sort=-modified-date&body-format=storage&status=current"
        if wanted:
            query += "&space-id=" + ",".join(spaces)
        path = f"/wiki/api/v2/pages?{query}" if (spaces or not wanted) else None
        stop = False
        while path and not stop:
            body = self._json("GET", path)
            for p in body.get("results") or []:
                changed = (p.get("version") or {}).get("createdAt") or p.get("createdAt") or ""
                if cursor and changed < cursor:
                    stop = True
                    break
                if wanted and str(p.get("spaceId")) not in spaces:
                    continue
                pages.append(p)
                if len(pages) >= self.max_pages:
                    notes.append(f"Read the {self.max_pages} most recently changed pages (max_pages).")
                    stop = True
                    break
            path = self._next(body)
        ids = sorted({a for p in pages for a in (p.get("ownerId"), p.get("authorId"), (p.get("version") or {}).get("authorId")) if a})
        self._names(ids)
        newest = cursor
        for i, p in enumerate(pages):
            if i % 25 == 0:
                report(step="read_confluence", done=1 + i / max(len(pages), 1), total=2)
            changed = (p.get("version") or {}).get("createdAt") or p.get("createdAt") or ""
            if not newest or changed > newest:
                newest = changed
            self._page(batch, p, spaces)
        report(step="read_confluence", done=2, total=2)
        batch.people = self.people.people
        batch.activity = list(dict.fromkeys(batch.activity))
        return SourceResult(batch=batch, cursor=newest, notes=notes, people_props=self.people.props)

    def _page(self, batch: Batch, p: dict, spaces: dict[str, tuple[str, str]]) -> None:
        doc_id = f"confluence:{p['id']}"
        title = p.get("title") or "Untitled"
        storage = ((p.get("body") or {}).get("storage") or {}).get("value") or ""
        text = html_to_text(storage[: self.max_page_chars])
        passages = passages_of(doc_id, split_passages(f"# {title}\n{text}" if text else ""))
        if not passages:
            return
        version = p.get("version") or {}
        updated = day(version.get("createdAt") or p.get("createdAt"))
        owner = self.people.get(p.get("ownerId") or p.get("authorId"))
        editor = self.people.get(version.get("authorId"))
        area = spaces.get(str(p.get("spaceId")))
        webui = (p.get("_links") or {}).get("webui") or ""
        url = f"{self.site}/wiki{webui}" if webui.startswith("/") else ""
        batch.docs.append(Doc(doc_id, "confluence_page", title, url, updated, author=owner,  # type: ignore[arg-type]
                              areas=(area[0],) if area else ()))
        batch.passages += passages
        if owner:
            batch.activity.append(Activity(owner, doc_id, "AUTHORED", day(p.get("createdAt")) or updated))
        if editor:
            batch.activity.append(Activity(editor, doc_id, "AUTHORED", updated))
