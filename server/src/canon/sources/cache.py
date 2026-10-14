"""An on-disk cache for raw downloads, under `/data/raw/<source>/` (gitignored).

A connector asks for a named piece of raw data and says how to fetch it. The first run fetches and writes the JSON;
every later run reads the file and makes no network call. Nothing reads this cache at answer time: it only makes
ingestion repeatable and cheap.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]


def data_dir() -> Path:
    """`CANON_DATA_DIR`, or `/data/` at the root of the repository."""
    return Path(os.environ.get("CANON_DATA_DIR") or REPO_ROOT / "data")


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, name: str) -> Path:
        return self.root / name

    def json(self, name: str, fetch: Callable[[], Any], *, refresh: bool = False) -> Any:
        """The cached value of `name`, fetching and storing it on the first call."""
        file = self.root / f"{name}.json"
        if file.exists() and not refresh:
            return json.loads(file.read_text())
        value = fetch()
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        tmp.replace(file)
        return value
