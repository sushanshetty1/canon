"""Uploaded files: each type read into passages, dated by its modified time, and archives opened safely."""

import io
import zipfile

import pytest

from canon.sources.archive import MAX_FILE, UploadError
from canon.sources.upload import File, UploadConnector, expand, safe_name


def quiet(**_):
    pass


def pdf(lines: list[str], title: str = "Travel policy") -> bytes:
    """A small, valid PDF with one page of text, written by hand."""
    text = " ".join(f"({line}) Tj T*" for line in lines)
    stream = f"BT /F1 12 Tf 14 TL 72 720 Td {text} ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Title ({title}) >>".encode(),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for o in offsets:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx(paragraphs: list[tuple[str, str | None]]) -> bytes:
    import docx as d

    document = d.Document()
    for text, style in paragraphs:
        document.add_paragraph(text, style=style)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def zipped(entries: dict[str, bytes], *, when=(2026, 9, 3, 10, 0, 0)) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(zipfile.ZipInfo(name, date_time=when), data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def read(files: list[File]):
    return UploadConnector(files, today="2026-10-15T00:00:00Z").read(cursor=None, report=quiet)


def test_each_file_type_becomes_an_upload_document():
    files = [
        File("handbook/expenses.md", b"---\ntitle: Expenses\n---\n# Expenses\n\nThe Finance team approves expenses over $500.\n", "2026-08-01T10:00:00Z"),
        File("notes.txt", b"Standups are at 9:30 every weekday.", None),
        File("oncall.html", b"<html><head><title>On-call</title><script>x()</script></head><body><h2>Rotation</h2><p>On-call rotates weekly.</p></body></html>", "2026-07-01T00:00:00Z"),
        File("travel.pdf", pdf(["Book travel through the travel desk.", "Economy class for flights under six hours."]), "2026-06-01T00:00:00Z"),
        File("security.docx", docx([("Security policy", "Title"), ("Laptops", "Heading 1"), ("Disks are encrypted.", None), ("Lock your screen", "List Bullet")]), None),
    ]
    result = read(files)
    docs = {d.id: d for d in result.batch.docs}
    assert set(docs) == {"upload:handbook-expenses-md", "upload:notes-txt", "upload:oncall-html", "upload:travel-pdf", "upload:security-docx"}
    assert all(d.kind == "upload" and d.url == "" for d in docs.values())
    assert docs["upload:handbook-expenses-md"].title == "Expenses" and docs["upload:handbook-expenses-md"].updated_at == "2026-08-01"
    assert docs["upload:notes-txt"].title == "notes" and docs["upload:notes-txt"].updated_at == "2026-10-15"  # no time: today
    assert docs["upload:oncall-html"].title == "On-call"
    assert docs["upload:travel-pdf"].title == "Travel policy"
    assert docs["upload:security-docx"].title == "Security policy"
    text = {d: "\n".join(p.text for p in result.batch.passages if p.doc_id == d) for d in docs}
    assert "The Finance team approves expenses over $500." in text["upload:handbook-expenses-md"]
    assert "On-call rotates weekly." in text["upload:oncall-html"] and "x()" not in text["upload:oncall-html"]
    assert "Book travel through the travel desk." in text["upload:travel-pdf"]
    assert "Disks are encrypted." in text["upload:security-docx"] and "- Lock your screen" in text["upload:security-docx"]


def test_zip_is_opened_safely():
    inner = zipped({"x.md": b"# Nested\n\nA page inside a zip inside the zip."})
    archive = zipped({
        "docs/../../etc/passwd.md": b"# Escape\n\nThis path tries to leave the upload.",
        "docs/runbook.md": b"# Runbook\n\nRestart the worker first.",
        "docs/inner.zip": inner,
        "__MACOSX/docs/._runbook.md": b"junk",
        "docs/image.png": b"\x89PNG",
    })
    notes: list[str] = []
    files = expand([File("export.zip", archive)], notes)
    names = sorted(f.name for f in files)
    # A path that tries to leave is never followed; a zip inside is read once, within the same limits.
    assert names == ["export/docs/inner.zip/x.md", "export/docs/runbook.md"]
    assert {f.modified for f in files} == {"2026-09-03T10:00:00Z"}
    # A zip bomb stops the upload, with the shared reader's message.
    bomb = zipped({"docs/bomb.txt": b"\0" * (MAX_FILE - 10)})
    with pytest.raises(UploadError, match="far more than its size"):
        expand([File("bomb.zip", bomb)], [])
    result = read([File("export.zip", archive)])
    assert {d.updated_at for d in result.batch.docs} == {"2026-09-03"}


def test_limits_are_enforced():
    with pytest.raises(UploadError, match="at most 200 files"):
        expand([File(f"{i}.txt", b"x") for i in range(201)], [])
    with pytest.raises(UploadError, match="at most 50 MB"):
        expand([File("a.txt", b"x" * (26 * 1024 * 1024)), File("b.txt", b"x" * (26 * 1024 * 1024))], [])
    notes: list[str] = []
    assert expand([File("big.txt", b"x" * (MAX_FILE + 1)), File("tool.exe", b"MZ")], notes) == []
    assert any("larger than 20 MB" in n for n in notes) and any("tool.exe is not a file Canon reads" in n for n in notes)
    assert safe_name("C:\\Users\\..\\..\\x.md") == "C:/Users/x.md" and safe_name("/etc/../x.md") == "etc/x.md"


def test_reuploading_a_file_keeps_its_document():
    first = read([File("policy.md", b"# Policy\n\nDeploys stop on Fridays.")])
    second = read([File("policy.md", b"# Policy\n\nDeploys may run on Fridays with approval.")])
    assert first.batch.docs[0].id == second.batch.docs[0].id
    assert first.batch.passages[0].id != second.batch.passages[0].id


def test_unreadable_files_are_noted_not_fatal():
    result = read([File("broken.pdf", b"%PDF-1.4 not really"), File("empty.txt", b"   "), File("ok.md", b"# Ok\n\nFine.")])
    assert [d.id for d in result.batch.docs] == ["upload:ok-md"]
    assert any("broken.pdf" in n for n in result.notes) and any("empty.txt" in n for n in result.notes)
