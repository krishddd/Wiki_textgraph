"""Phase C tests: the console file-ingest core (multipart, sanitisation, rebuild)."""

from pathlib import Path

from textgraph.console.ingest import allowed, ingest_files, parse_multipart, sanitize_name
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build


def test_sanitize_name_blocks_traversal_and_junk() -> None:
    assert sanitize_name("../../etc/passwd") == "passwd"
    assert sanitize_name("a b/c.md") == "c.md"
    assert sanitize_name("....md") == "md"  # leading dots stripped
    assert sanitize_name("weird name!@#.txt") == "weird_name___.txt"


def test_allowed_extensions() -> None:
    assert allowed("notes.md") and allowed("data.json") and allowed("log.log")
    assert not allowed("virus.exe") and not allowed("scan.pdf")


def test_parse_multipart_preserves_file_content() -> None:
    body = (
        b"--B\r\n"
        b'Content-Disposition: form-data; name="file"; filename="a.md"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
        b"# Title\n\nAcme Corp controls Beta Ltd.\r\n"
        b"--B--\r\n"
    )
    files = parse_multipart("multipart/form-data; boundary=B", body)
    assert files == [("a.md", b"# Title\n\nAcme Corp controls Beta Ltd.")]


def test_parse_multipart_ignores_non_file_parts() -> None:
    assert parse_multipart("text/plain", b"nope") == []  # no boundary


def test_ingest_adds_a_document_and_its_entities(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"# Case\n\nAcme Corp controls Beta Ltd.\n")
    before = QueryEngine(*_ne(build(corpus)))
    before_names = {before._name(n) for n in before._entity_ids}
    assert "Zeta Corp" not in before_names  # not there yet

    res = ingest_files(
        corpus,
        [("notes.md", b"# Annex\n\nZeta Corp controls Omega Bank.\n")],
        cache_dir=tmp_path / "cache",
    )
    assert res.ok and res.written == ["notes.md"] and not res.rejected
    after = QueryEngine(res.nodes, res.edges)
    after_names = {after._name(n) for n in after._entity_ids}
    assert "Zeta Corp" in after_names and "Omega Bank" in after_names  # new entities landed
    assert (corpus / "notes.md").exists()


def test_ingest_rejects_unsupported_and_writes_nothing(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"Acme Corp controls Beta Ltd.\n")
    res = ingest_files(corpus, [("x.exe", b"MZ...")], cache_dir=tmp_path / "cache")
    assert not res.ok and res.rejected == ["x.exe"]
    assert not (corpus / "x.exe").exists()  # rejected files never touch disk


def _ne(result: object) -> tuple[list, list]:
    return result.nodes, result.edges  # type: ignore[attr-defined]
