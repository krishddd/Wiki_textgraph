from pathlib import Path

import pytest
from textgraph import __version__
from textgraph.cli import main


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_build_command_writes_artifact_dir(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"# Title\n\nSome content. WHY: because.\n")
    out = tmp_path / "out"

    assert main(["build", str(corpus), "-o", str(out)]) == 0
    for name in ("graph.json", "GRAPH_REPORT.md", "graph.html", "schema.yaml", "manifest.json"):
        assert (out / name).exists(), name
    assert (out / "graph.json").read_bytes().endswith(b"\n")


def test_build_json_only(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.txt").write_bytes(b"hello world")
    out = tmp_path / "graph.json"

    assert main(["build", str(corpus), "--json-only", str(out)]) == 0
    assert out.exists()
    assert out.read_bytes().endswith(b"\n")


def test_build_missing_path_errors(tmp_path: Path) -> None:
    assert main(["build", str(tmp_path / "nope")]) == 2


DOCS = str(Path(__file__).parent.parent / "fixtures" / "corpora" / "docs")
TEMPORAL = str(Path(__file__).parent.parent / "fixtures" / "corpora" / "temporal")


@pytest.mark.parametrize(
    ("argv", "needle"),
    [
        (["query", DOCS, "who transferred funds"], "search:"),
        (["path", DOCS, "Acme Corp", "Gamma Holdings"], "path 1"),
        (["explain", DOCS, "Acme Corp"], "why: Acme Corp"),
        (["neighbors", DOCS, "Acme Corp"], "neighbors of Acme Corp"),
        (["timeline", TEMPORAL, "Acme Corp"], "timeline: Acme Corp"),
        (["contradictions", TEMPORAL], "contradictions: 1"),
        (["communities", DOCS], "communities:"),
        (["stats", DOCS], "stats:"),
    ],
)
def test_query_verbs(argv: list[str], needle: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert needle in capsys.readouterr().out


def test_explain_shows_superseded_window(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", TEMPORAL, "Acme Corp"]) == 0
    assert "SUPERSEDED" in capsys.readouterr().out


def test_query_verb_missing_path_errors(tmp_path: Path) -> None:
    assert main(["stats", str(tmp_path / "nope")]) == 2
