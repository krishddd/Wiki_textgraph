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
SECURE = str(Path(__file__).parent.parent / "fixtures" / "corpora" / "secure")


def test_secure_command_enforces_policy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from textgraph.l8_retrieval import QueryEngine
    from textgraph.pipeline import build

    # Grant alice the public document only (transitively, via group + folder).
    r = build(Path(SECURE))
    qe = QueryEngine(r.nodes, r.edges)
    pub = sorted(qe._node_docs[qe.resolve("Gamma Holdings")])[0]
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "tuples": [
                    ["group:analysts", "member", "user:alice"],
                    ["folder:cases", "viewer", "group:analysts"],
                    [f"doc:{pub}", "parent", "folder:cases"],
                ]
            }
        )
    )
    argv = [
        "secure",
        SECURE,
        "shadow phantom transferred funds",
        "--policy",
        str(policy),
        "--principal",
        "alice",
        "--group",
        "analysts",
    ]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "principal: alice" in out
    assert "Shadow" not in out and "Phantom" not in out  # no context-bleed


def test_reason_command_prints_a_grounded_chain(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reason", DOCS, "how is Acme Corp connected to Delta Trust"]) == 0
    out = capsys.readouterr().out
    assert "grounded: True" in out
    assert "[Plan]" in out and "[Hypothesis]" in out and "[DistilledSummary]" in out
    assert "answer:" in out


def test_reason_command_static_mode_is_bounded(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["reason", DOCS, "who is John Doe", "--mode", "static"]) == 0
    assert "mode: static" in capsys.readouterr().out


def test_secure_command_missing_policy_errors() -> None:
    assert main(["secure", SECURE, "q", "--policy", "nope.json", "--principal", "alice"]) == 2


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
