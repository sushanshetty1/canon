"""Reading an uploaded zip safely, for every kind of upload: exports (`canon.sources.uploads`) and files
(`canon.sources.upload`).

A zip is read in memory, never unpacked to disk, so a path inside it cannot escape anywhere. One set of limits holds
for every upload: the bytes sent, each file unpacked, everything unpacked together, how many entries there are, and
how far a file may have been compressed, so a small zip that unpacks to gigabytes is refused before it is read. The
sizes in a zip's headers can lie, so every read is capped at the limit whatever they say. A zip inside the zip is read
once more, within the same budget.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

MAX_UPLOAD = 50 * 1024 * 1024  # bytes sent
MAX_FILE = 20 * 1024 * 1024  # one file inside, unpacked
MAX_TOTAL = 250 * 1024 * 1024  # everything read, unpacked
MAX_FILES = 20_000  # entries in the archive
MAX_RATIO = 150  # how far a file may have been compressed


class UploadError(ValueError):
    """The upload cannot be read. The message is safe to show."""

    @property
    def public_message(self) -> str:
        return str(self)


@dataclass
class _Budget:
    files: int = 0
    total: int = 0


def read_zip(
    data: bytes,
    suffixes: tuple[str, ...],
    *,
    budget: _Budget | None = None,
    depth: int = 0,
    dates: dict[str, str] | None = None,
) -> dict[str, bytes]:
    """The files in a zip whose names end in `suffixes`, by their path inside. A zip inside the zip (Notion splits
    big exports into parts) is read once more, within the same limits. `dates`, when given, is filled with each
    file's modified time inside the zip (ISO, UTC)."""
    if len(data) > MAX_UPLOAD:
        raise UploadError("An upload can be at most 50 MB.")
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
                raise UploadError("The zip holds too many files.")
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
                raise UploadError("The zip is encrypted.")
            if info.file_size > MAX_FILE and not nested:
                raise UploadError("A file in the upload is larger than 20 MB.")
            if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise UploadError("The zip unpacks to far more than its size. It was not read.")
            if budget.total + info.file_size > MAX_TOTAL:
                raise UploadError("The zip unpacks to more than 250 MB.")
            limit = MAX_UPLOAD if nested else MAX_FILE
            with archive.open(info) as f:
                blob = f.read(limit + 1)  # the size in the header can lie: never read past the limit
            if len(blob) > limit:
                raise UploadError("A file in the zip is larger than it says.")
            if nested:
                inner_dates: dict[str, str] | None = {} if dates is not None else None
                out.update({f"{name}/{k}": v for k, v in read_zip(blob, suffixes, budget=budget, depth=1, dates=inner_dates).items()})
                if dates is not None and inner_dates:
                    dates.update({f"{name}/{k}": v for k, v in inner_dates.items()})
                continue
            budget.total += len(blob)
            if budget.total > MAX_TOTAL:
                raise UploadError("The zip unpacks to more than 250 MB.")
            out[name] = blob
            if dates is not None:
                try:
                    dates[name] = datetime(*info.date_time, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    pass
    return out
