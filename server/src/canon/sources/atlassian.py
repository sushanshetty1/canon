"""What Jira Cloud and Confluence Cloud share: the site address, and an email with an API token.

The site must be an Atlassian Cloud site (`https://<name>.atlassian.net`). Canon calls only that host, so a
connection can never point the server at an address of someone's choosing.
"""

import re
from urllib.parse import urlparse

from canon.sources.client import SourceError

_SITE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net$")


def site_url(value: str | None) -> str:
    """`acme`, `acme.atlassian.net` or `https://acme.atlassian.net/jira/...` -> `https://acme.atlassian.net`."""
    text = (value or "").strip().lower()
    if not text:
        raise SourceError("Give the site address, like acme.atlassian.net.")
    if "://" not in text:
        text = "https://" + text
    host = urlparse(text).hostname or ""
    if "." not in host:
        host += ".atlassian.net"
    if not _SITE.match(host):
        raise SourceError("Canon connects to Atlassian Cloud sites only, like acme.atlassian.net.")
    return f"https://{host}"


def credentials(email: str | None, token: str | None) -> tuple[str, str]:
    email = (email or "").strip()
    if "@" not in email:
        raise SourceError("Give the email address of the Atlassian account the API token belongs to.")
    if not (token or "").strip():
        raise SourceError("Paste an Atlassian API token.")
    return email, token.strip()
