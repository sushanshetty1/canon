"""Small synthetic exports for tests and the live check: a Slack export, a Notion export and a Confluence export from
a made-up company, Kestrel. No real people or messages.

    python tests/exports.py <dir>   writes kestrel-slack.zip, kestrel-notion.zip and kestrel-confluence.zip
"""

import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def ts(when: str) -> str:
    return f"{datetime.fromisoformat(when).replace(tzinfo=UTC).timestamp():.6f}"


USERS = [
    {"id": "U01", "name": "maya", "real_name": "Maya Lindqvist", "profile": {"display_name": "Maya L", "real_name": "Maya Lindqvist"}},
    {"id": "U02", "name": "tomas", "real_name": "Tomas Okafor", "profile": {"display_name": "", "real_name": "Tomas Okafor"}},
    {"id": "U03", "name": "priya", "real_name": "Priya Raman", "profile": {"display_name": "Priya", "real_name": "Priya Raman"}},
    {"id": "B01", "name": "deploybot", "is_bot": True, "profile": {"display_name": "deploybot"}},
]
CHANNELS = [
    {"id": "C01", "name": "eng-deploys", "created": 1767225600},
    {"id": "C02", "name": "payments", "created": 1767225600},
]


def slack_messages() -> dict[str, list[dict]]:
    parent = ts("2026-09-01T09:00:00")
    return {
        "eng-deploys/2026-09-01.json": [
            {"type": "message", "user": "U01", "ts": parent, "thread_ts": parent, "reply_count": 2,
             "text": "Proposal: should we stop deploying on Fridays? Two incidents last month came from Friday deploys."},
            {"type": "message", "user": "U02", "ts": ts("2026-09-01T09:20:00"), "thread_ts": parent,
             "text": "Agreed. <@U01> let's make it a rule."},
            {"type": "message", "user": "U01", "ts": ts("2026-09-01T10:05:00"), "thread_ts": parent,
             "text": "We decided: going forward there are no production deploys on Fridays. Hotfixes need approval from the on-call lead."},
            {"type": "message", "user": "U01", "ts": ts("2026-09-01T10:06:00"), "thread_ts": parent,
             "text": "I will update the handbook page in <#C01|eng-deploys>."},
            {"type": "message", "subtype": "channel_join", "user": "U03", "ts": ts("2026-09-01T11:00:00"), "text": "<@U03> has joined the channel"},
            {"type": "message", "bot_id": "B01", "user": "B01", "ts": ts("2026-09-01T12:00:00"), "text": "Deploy 412 finished"},
        ],
        "payments/2026-09-03.json": [
            {"type": "message", "user": "U03", "ts": ts("2026-09-03T14:00:00"),
             "text": "Heads up: refunds moved to the Payments team. The Billing team no longer owns refunds &amp; chargebacks."},
            {"type": "message", "user": "U03", "ts": ts("2026-09-03T14:02:00"),
             "text": "Ask in <#C02|payments> or ping <@U02> for anything about refunds. See <https://example.com/refunds|the refunds doc>."},
            {"type": "message", "user": "U02", "ts": ts("2026-09-03T14:20:00"), "text": "Thanks!"},
        ],
    }


def slack_zip(*, wrap: str = "") -> bytes:
    buf = io.BytesIO()
    prefix = f"{wrap}/" if wrap else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{prefix}users.json", json.dumps(USERS))
        z.writestr(f"{prefix}channels.json", json.dumps(CHANNELS))
        z.writestr(f"{prefix}dms.json", json.dumps([{"id": "D01", "members": ["U01", "U02"]}]))
        z.writestr(f"{prefix}D01/2026-09-02.json", json.dumps([{"type": "message", "user": "U01", "ts": ts("2026-09-02T08:00:00"), "text": "A private note"}]))
        for name, rows in slack_messages().items():
            z.writestr(f"{prefix}{name}", json.dumps(rows))
    return buf.getvalue()


NOTION_PAGES = {
    "Kestrel Wiki 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/On-call 0f1e2d3c4b5a69788796a5b4c3d2e1f0.md": """# On-call

Owner: Platform team
Last edited time: August 14, 2026 3:12 PM

## Rotation

The Platform team runs the on-call rotation. Each shift is one week and starts on Monday.

## Escalation

Escalate a page that is not acknowledged in 15 minutes to the on-call lead.
""",
    "Kestrel Wiki 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/Expenses 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b.md": """# Expenses

Created: March 3, 2026 9:00 AM

Expenses under 200 euros need no approval. Anything larger needs a lead's approval.
""",
}


def notion_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in NOTION_PAGES.items():
            z.writestr(name, text)
        z.writestr("Kestrel Wiki 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/image.png", b"\x89PNG not read")
    return buf.getvalue()


CONFLUENCE_PAGE = """<!DOCTYPE html>
<html><head><title>ENG : Release process</title><style>body { color: red }</style></head>
<body>
<div id="main-header"><div id="breadcrumb-section"><ol id="breadcrumbs"><li><a href="index.html">Engineering</a></li></ol></div>
<h1 id="title-heading"><span id="title-text">ENG : Release process</span></h1></div>
<div class="page-metadata">Created by <span class="author">Tomas Okafor</span>, last modified on Jul 21, 2026</div>
<div id="main-content" class="wiki-content group">
<h2>Releases</h2>
<p>The Release team ships every Tuesday. A release needs one approval from the Release team lead.</p>
<ul><li>Freeze on Monday at noon</li><li>Ship on Tuesday</li></ul>
</div>
<div id="footer"><section class="footer-body"><p>Document generated by Confluence on Sep 10, 2026 10:00</p></section></div>
</body></html>
"""


def confluence_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ENG/index.html", "<html><head><title>ENG</title></head><body><p>Confluence space index</p></body></html>")
        z.writestr("ENG/Release-process_98307.html", CONFLUENCE_PAGE)
    return buf.getvalue()


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "kestrel-slack.zip").write_bytes(slack_zip(wrap="Kestrel Slack export Sep 1 2026 - Sep 10 2026"))
    (out / "kestrel-notion.zip").write_bytes(notion_zip())
    (out / "kestrel-confluence.zip").write_bytes(confluence_zip())
    print(f"Wrote three exports to {out}")
