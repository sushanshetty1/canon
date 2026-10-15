"""Slack, through a bot token (`xoxb-`): the conversations in the channels the bot was invited to.

What it reads:

- **Channels** the bot is a member of (`conversations.list`, public, and private when the app has the `groups:`
  scopes). `config["channels"]` can narrow it to some channel names or ids.
- **Threads.** A message with replies and its replies (`conversations.replies`) become one `slack_thread` document.
- **The rest of a channel's day.** Top-level messages without replies are grouped by channel and day into one
  `slack_thread` document, so a quick exchange is read in context.
- **Passages** are conversation turns: consecutive messages by one person on one day are one run, headed by who
  said it and when (`Ana Ruiz, 2026-10-14:`), and the passage keeps its author, as every chat source does.
- **People** by display name and Slack id. When the app may read emails (`users:read.email`) the person is matched
  across sources by a hash of their email; the email is never stored.
- **Activity.** A thread's starter authored it, people who replied commented on it.

Incremental: the cursor keeps, per channel, the timestamp of the newest message read. The next sync starts a few
days before it (`rethread_days`), from the start of that day, so new replies to recent threads are seen and a day's
document is always read whole. Volume is bounded per sync: channels, messages per channel, threads per channel and
replies per thread, each with a default and a hard maximum.
"""

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

from canon.sources.client import Client, SourceError, capped, status_error
from canon.sources.connector import Report
from canon.sources.identity import People, SourceResult
from canon.sources.text import Turn, turn_passages
from canon.types import Activity, Batch, Doc

API = "https://slack.com/api"
REQUIRED_SCOPES = ("channels:history", "channels:read", "users:read")
SKIP_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name", "channel_archive",
                 "channel_unarchive", "group_join", "group_leave", "pinned_item", "unpinned_item", "bot_add", "bot_remove"}

_AUTH = {"invalid_auth", "not_authed", "token_revoked", "account_inactive", "token_expired", "no_permission"}


def slack_error(method: str, body: dict) -> SourceError:
    error = body.get("error") or "unknown_error"
    if error in _AUTH:
        return SourceError("Slack did not accept this token. Copy the Bot User OAuth Token (xoxb-) again.")
    if error == "missing_scope":
        needed = body.get("needed") or "a scope"
        return SourceError(f"The Slack app is missing the {needed} scope. Add it under OAuth & Permissions, then reinstall the app.")
    if error == "ratelimited":
        return SourceError("Slack is rate limiting Canon. The next sync will carry on from here.", status=429)
    if error == "not_in_channel":
        return SourceError("The Slack app is not in that channel. Invite it with /invite.")
    return SourceError(f"Slack answered {method} with an error ({error}).")


def _ts(ts: str | None) -> float:
    try:
        return float(ts or 0)
    except ValueError:
        return 0.0


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _day_start(t: float) -> float:
    d = datetime.fromtimestamp(t, UTC)
    return datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()


class SlackConnector:
    kind = "slack"
    label = "Slack"

    def __init__(
        self,
        token: str,
        config: dict | None = None,
        *,
        http: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ):
        self.config = config or {}
        self.client = Client("Slack", http=http, headers={"Authorization": f"Bearer {token}"}, sleep=sleep)
        self.now = now
        self.max_channels = capped(self.config, "max_channels", 20, 100)
        self.max_messages = capped(self.config, "max_messages", 1000, 5000)  # per channel, per sync
        self.max_threads = capped(self.config, "max_threads", 200, 1000)  # per channel, per sync
        self.max_replies = capped(self.config, "max_replies", 200, 1000)  # per thread
        self.lookback_days = capped(self.config, "lookback_days", 90, 365)
        self.rethread_days = capped(self.config, "rethread_days", 7, 30)
        self.people = People("slack")
        self._users: dict[str, dict | None] = {}
        self.team_id = ""
        self.base_url = ""

    # ----- the API

    def _call(self, method: str, **params) -> dict:
        r = self.client.request("GET", f"{API}/{method}", params={k: v for k, v in params.items() if v is not None})
        if r.status_code != 200:
            raise status_error("Slack", r.status_code)
        body = r.json()
        if not body.get("ok"):
            raise slack_error(method, body)
        return body

    def check(self) -> dict:
        """One cheap call (`auth.test`) that says whether the token works and has the scopes Canon needs."""
        r = self.client.request("GET", f"{API}/auth.test")
        if r.status_code != 200:
            raise status_error("Slack", r.status_code)
        body = r.json()
        if not body.get("ok"):
            raise slack_error("auth.test", body)
        granted = {s.strip() for s in (r.headers.get("x-oauth-scopes") or "").split(",") if s.strip()}
        if granted:
            missing = [s for s in REQUIRED_SCOPES if s not in granted]
            if missing:
                raise SourceError(
                    f"The Slack app is missing the {', '.join(missing)} scope{'s' if len(missing) > 1 else ''}. "
                    "Add it under OAuth & Permissions, then reinstall the app."
                )
        self.team_id = body.get("team_id") or ""
        self.base_url = (body.get("url") or "https://slack.com/").rstrip("/") + "/"
        return {"team": body.get("team") or "", "team_id": self.team_id, "url": self.base_url,
                "private": "groups:history" in granted}

    def _pages(self, method: str, key: str, limit: int, **params):
        """Items of a cursor-paginated method, newest first where Slack orders them so, at most `limit`."""
        cursor = None
        got = 0
        while True:
            body = self._call(method, limit=min(200, limit), cursor=cursor, **params)
            for item in body.get(key) or []:
                yield item
                got += 1
                if got >= limit:
                    return
            cursor = (body.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return

    def user(self, user_id: str | None) -> str | None:
        """The handle of a Slack user, looked up once (`users.info`)."""
        if not user_id:
            return None
        if user_id not in self._users:
            info = None
            if len(self._users) < 2000:
                try:
                    info = self._call("users.info", user=user_id).get("user")
                except SourceError as e:
                    if e.status == 429:
                        raise
            self._users[user_id] = info
        info = self._users[user_id]
        if info is None:
            return self.people.add(user_id, None)
        if info.get("is_bot") or info.get("id") == "USLACKBOT":
            return None
        profile = info.get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or info.get("real_name") or info.get("name")
        return self.people.add(user_id, name, profile.get("email"))

    # ----- text

    def clean(self, text: str) -> str:
        def mention(m: re.Match) -> str:
            handle = self.user(m.group(1))
            return "@" + (self.people.name(m.group(1)) or "someone") if handle else "@someone"

        text = re.sub(r"<@([UW][A-Z0-9]+)(\|[^>]*)?>", mention, text or "")
        text = re.sub(r"<#[CG][A-Z0-9]+\|([^>]*)>", r"#\1", text)
        text = re.sub(r"<!(here|channel|everyone)[^>]*>", r"@\1", text)
        text = re.sub(r"<!subteam\^[A-Z0-9]+\|([^>]*)>", r"\1", text)
        text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2", text)
        text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
        text = re.sub(r"```.*?```", "", text, flags=re.S)  # code is not knowledge about the company
        return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()

    def _author(self, m: dict) -> tuple[str | None, str]:
        """(handle or None for a bot, the name to show)."""
        if m.get("user") and not m.get("bot_id"):
            handle = self.user(m["user"])
            return handle, self.people.name(m["user"]) or "Someone"
        bot = m.get("username") or (m.get("bot_profile") or {}).get("name") or "A bot"
        return None, bot

    def _passages(self, doc_id: str, messages: list[dict]) -> list:
        """Message runs as conversation turns (`canon.sources.text.turn_passages`): each passage says who said it and
        when, and keeps its author, so the graph knows who said what."""
        turns = []
        for m in messages:
            text = self.clean(m.get("text") or "")
            if not text:
                continue
            handle, name = self._author(m)
            when = datetime.fromtimestamp(_ts(m.get("ts")), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            turns.append(Turn(name, when, text, handle))
        return turn_passages(doc_id, turns, merge=True)

    def _link(self, channel: str, ts: str | None = None) -> str:
        base = self.base_url or "https://slack.com/"
        return f"{base}archives/{channel}" + (f"/p{ts.replace('.', '')}" if ts else "")

    # ----- reading

    def channels(self, notes: list[str]) -> list[dict]:
        wanted = {str(c).lstrip("#").lower() for c in self.config.get("channels") or []}
        try:
            found = list(self._pages("conversations.list", "channels", 2000, types="public_channel,private_channel",
                                     exclude_archived="true"))
        except SourceError as e:
            if "groups:read" not in str(e) and "missing" not in str(e):
                raise
            notes.append("Private channels need the groups:read and groups:history scopes; only public ones were read.")
            found = list(self._pages("conversations.list", "channels", 2000, types="public_channel", exclude_archived="true"))
        mine = [c for c in found if c.get("is_member") and not c.get("is_archived")]
        if wanted:
            mine = [c for c in mine if c.get("id", "").lower() in wanted or (c.get("name") or "").lower() in wanted]
        if not mine:
            notes.append("The Slack app is not in any channel yet. Invite it to a channel with /invite @YourApp.")
        if len(mine) > self.max_channels:
            notes.append(f"Read {self.max_channels} of the {len(mine)} channels the app is in (max_channels).")
        return mine[: self.max_channels]

    def read(self, *, cursor: str | None, report: Report) -> SourceResult:
        state = json.loads(cursor) if cursor else {}
        seen: dict[str, str] = dict(state.get("channels") or {})
        notes: list[str] = []
        report(step="read_slack", done=0, total=1)
        self.check()
        channels = self.channels(notes)
        batch = Batch()
        now = self.now()
        floor = now - self.lookback_days * 86400
        for i, ch in enumerate(channels):
            report(step="read_slack", done=i, total=len(channels))
            cid, cname = ch["id"], ch.get("name") or ch["id"]
            last = _ts(seen.get(cid))
            start = _day_start(max(floor, last - self.rethread_days * 86400) if last else floor)
            try:
                messages = list(self._pages("conversations.history", "messages", self.max_messages + 1, channel=cid,
                                            oldest=f"{start:.6f}", inclusive="true"))
            except SourceError as e:
                if e.status == 429:
                    raise
                notes.append(f"#{cname} could not be read: {e}")
                continue
            truncated = len(messages) > self.max_messages
            messages = messages[: self.max_messages]
            if truncated:
                notes.append(f"#{cname} had more than {self.max_messages} messages since the last sync; the newest were read.")
            self._channel(batch, cid, cname, messages, truncated, notes)
            if messages:
                newest = max(messages, key=lambda m: _ts(m.get("ts")))["ts"]
                if _ts(newest) > last:
                    seen[cid] = newest
        report(step="read_slack", done=len(channels), total=len(channels))
        batch.activity = list(dict.fromkeys(batch.activity))
        batch.people = self.people.people
        return SourceResult(batch=batch, cursor=json.dumps({"channels": seen}, sort_keys=True), notes=notes,
                            people_props=self.people.props)

    def _channel(self, batch: Batch, cid: str, cname: str, messages: list[dict], truncated: bool, notes: list[str]) -> None:
        messages = [m for m in messages if m.get("subtype") not in SKIP_SUBTYPES and m.get("ts")]
        messages.sort(key=lambda m: _ts(m["ts"]))
        # A reply also posted to the channel is read with its thread.
        top = [m for m in messages if not m.get("thread_ts") or m.get("thread_ts") == m.get("ts")]
        threads = [m for m in top if (m.get("reply_count") or 0) > 0]
        loose = [m for m in top if not (m.get("reply_count") or 0)]
        if len(threads) > self.max_threads:
            notes.append(f"#{cname}: read the newest {self.max_threads} of {len(threads)} threads (max_threads).")
            threads = threads[-self.max_threads :]
        for parent in threads:
            try:
                replies = list(self._pages("conversations.replies", "messages", self.max_replies + 1, channel=cid, ts=parent["ts"]))
            except SourceError as e:
                if e.status == 429:
                    raise
                replies = [parent]
            replies = [m for m in replies if m.get("subtype") not in SKIP_SUBTYPES and m.get("ts")]
            replies.sort(key=lambda m: _ts(m["ts"]))
            replies = replies[: self.max_replies]
            if not replies or replies[0].get("ts") != parent["ts"]:
                replies = [parent, *[r for r in replies if r.get("ts") != parent["ts"]]]
            self._thread_doc(batch, cid, cname, replies)
        # Loose messages by day. A truncated read may have cut the oldest day short: leave it for a later sync.
        by_day: dict[str, list[dict]] = {}
        for m in loose:
            by_day.setdefault(_day(_ts(m["ts"])), []).append(m)
        if truncated and by_day:
            by_day.pop(min(by_day), None)
        for day, msgs in sorted(by_day.items()):
            self._day_doc(batch, cid, cname, day, msgs)

    def _thread_doc(self, batch: Batch, cid: str, cname: str, msgs: list[dict]) -> None:
        parent = msgs[0]
        doc_id = f"slack:{self.team_id.lower() or 'team'}:{cid.lower()}:{parent['ts']}"
        first = self.clean(parent.get("text") or "").splitlines()[0] if self.clean(parent.get("text") or "") else "a thread"
        title = f"#{cname}: {first[:80]}"
        passages = self._passages(doc_id, msgs)
        if not passages:
            return
        starter, _ = self._author(parent)
        batch.docs.append(Doc(doc_id, "slack_thread", title, self._link(cid, parent["ts"]),  # type: ignore[arg-type]
                              _day(_ts(msgs[-1]["ts"])), author=starter))
        batch.passages += passages
        if starter:
            batch.activity.append(Activity(starter, doc_id, "AUTHORED", _day(_ts(parent["ts"]))))
        for m in msgs[1:]:
            handle, _ = self._author(m)
            if handle and handle != starter:
                batch.activity.append(Activity(handle, doc_id, "COMMENTED", _day(_ts(m["ts"]))))

    def _day_doc(self, batch: Batch, cid: str, cname: str, day: str, msgs: list[dict]) -> None:
        doc_id = f"slack:{self.team_id.lower() or 'team'}:{cid.lower()}:{day}"
        passages = self._passages(doc_id, msgs)
        if not passages:
            return
        first_author, _ = self._author(msgs[0])
        batch.docs.append(Doc(doc_id, "slack_thread", f"#{cname} on {day}", self._link(cid, msgs[0]["ts"]),  # type: ignore[arg-type]
                              day, author=first_author))
        batch.passages += passages
        for m in msgs:
            handle, _ = self._author(m)
            if handle:
                batch.activity.append(Activity(handle, doc_id, "AUTHORED", day))
