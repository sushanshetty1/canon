"""Rich text from other tools to the plain Markdown-like text passages are split from.

- `html_to_text`: HTML pages and Confluence's storage format (XHTML with `ac:` macros). Headings become `#` lines,
  so `split_passages` keeps each section's heading with it; lists become `-` lines; tables become `a | b` rows;
  scripts, styles and code blocks are dropped (code is not knowledge about the company).
- `adf_to_text`: the Atlassian Document Format Jira Cloud returns for descriptions and comments.
"""

import re
from html import unescape
from html.parser import HTMLParser

_BLOCK = {"p", "div", "section", "article", "blockquote", "br", "tr", "table", "ul", "ol", "dl", "dt", "dd", "hr",
          "ac:layout-section", "ac:layout-cell", "ac:task", "ac:rich-text-body"}
_SKIP = {"script", "style", "head", "title", "noscript", "svg", "template", "pre", "code", "ac:plain-text-body",
         "ac:parameter"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.cells: list[str] | None = None
        self.cell: list[str] | None = None

    def _emit(self, text: str) -> None:
        if self.cell is not None:
            self.cell.append(text)
        else:
            self.out.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "tr":
            self.cells = []
        elif tag in ("td", "th") and self.cells is not None:
            self.cell = []
        elif tag in _BLOCK:
            if self.out and self.out[-1] == "\n- ":
                return  # a paragraph inside a list item stays on the item's line
            self.out.append("\n\n" if tag in ("p", "div", "blockquote", "table") else "\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n")
        elif tag == "li" and self.out and self.out[-1] == "\n- ":
            self.out.pop()  # an empty item
        elif tag in ("td", "th") and self.cells is not None and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            row = " | ".join(c for c in self.cells if c)
            if row:
                self.out.append("\n" + row)
            self.cells = None
        elif tag in ("p", "div", "blockquote", "table"):
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.skip:
            self._emit("\n")

    def handle_data(self, data):
        if not self.skip:
            self._emit(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()
    text = "".join(parser.out).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"^(#+|-)\s*$", "", text, flags=re.M)  # empty headings and items
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I) or re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S | re.I)
    if not m:
        return None
    title = " ".join(unescape(re.sub(r"<[^>]+>", "", m.group(1))).split())
    return title or None


# ----- Atlassian Document Format -----------------------------------------------------------------------------------

_ADF_SKIP = {"codeBlock", "media", "mediaSingle", "mediaGroup", "extension", "bodiedExtension", "inlineCard"}


def adf_to_text(node) -> str:
    """ADF (a dict tree) to text. A plain string (Jira's v2 API) passes through."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    out: list[str] = []

    def walk(n, depth: int = 0) -> None:
        if not isinstance(n, dict) or depth > 40:
            return
        kind = n.get("type")
        if kind in _ADF_SKIP:
            return
        if kind == "text":
            out.append(n.get("text") or "")
            return
        if kind == "mention":
            out.append((n.get("attrs") or {}).get("text") or "")
            return
        if kind == "emoji":
            out.append((n.get("attrs") or {}).get("text") or "")
            return
        if kind == "hardBreak":
            out.append("\n")
            return
        if kind == "heading":
            level = int((n.get("attrs") or {}).get("level") or 2)
            out.append("\n\n" + "#" * max(1, min(level, 6)) + " ")
        elif kind == "listItem":
            out.append("\n- ")
        elif kind == "tableRow":
            out.append("\n")
        elif kind == "tableCell" or kind == "tableHeader":
            out.append(" | ")
        elif kind in ("paragraph", "blockquote", "panel", "rule"):
            if not (out and out[-1] == "\n- "):  # a paragraph inside a list item stays on the item's line
                out.append("\n\n")
        for child in n.get("content") or []:
            walk(child, depth + 1)
        if kind == "heading":
            out.append("\n\n")
        elif kind in ("paragraph", "blockquote", "panel"):
            out.append("\n")

    walk(node)
    text = "".join(out)
    lines = [re.sub(r"[ \t]+", " ", line).strip(" |").strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"^(#+|-)\s*$", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
