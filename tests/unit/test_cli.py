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


def _mk_corpus(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "f.md").write_text(text, encoding="utf-8")
    return d


def test_diff_command_reports_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = _mk_corpus(tmp_path, "a", "# Case\nAcme Corp controls Beta Ltd.\n")
    b = _mk_corpus(
        tmp_path,
        "b",
        "# Case\nAcme Corp controls Beta Ltd.\nZeta Corp transferred $9 to Acme Corp.\n",
    )
    assert main(["diff", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "Zeta Corp" in out and "TRANSFERRED" in out


def test_diff_command_json_and_no_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _mk_corpus(tmp_path, "a", "# Case\nAcme Corp controls Beta Ltd.\n")
    assert main(["diff", str(a), str(a), "--json"]) == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["added_entities"] == 0
    # And the human path on identical inputs.
    assert main(["diff", str(a), str(a)]) == 0
    assert "No changes." in capsys.readouterr().out


def test_diff_command_missing_path_errors(tmp_path: Path) -> None:
    a = _mk_corpus(tmp_path, "a", "# Case\nAcme Corp controls Beta Ltd.\n")
    assert main(["diff", str(a), str(tmp_path / "nope")]) == 2


def test_federate_command_finds_and_profiles_shared_entities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = tmp_path / "caseA"
    b = tmp_path / "caseB"
    for d, text in (
        (a, "# A\nJohn Doe is director of Acme Corp.\n"),
        (b, "# B\nJohn Doe transferred $500 to Delta Trust.\n"),
    ):
        assert main(["build", str(_mk_corpus(tmp_path, d.name + "src", text)), "-o", str(d)]) == 0
    ga, gb = str(a / "graph.json"), str(b / "graph.json")
    assert main(["federate", ga, gb]) == 0
    assert "John Doe" in capsys.readouterr().out
    # dossier
    assert main(["federate", ga, gb, "--entity", "John Doe"]) == 0
    dossier = capsys.readouterr().out
    assert "DIRECTOR_OF" in dossier and "TRANSFERRED" in dossier
    # json + a missing entity + min-cases that excludes everything
    assert main(["federate", ga, gb, "--json"]) == 0
    assert main(["federate", ga, gb, "--entity", "Nobody"]) == 0
    assert "not found" in capsys.readouterr().out
    assert main(["federate", ga, gb, "--min-cases", "3"]) == 0
    assert "No entities shared" in capsys.readouterr().out


def test_federate_command_missing_path_errors(tmp_path: Path) -> None:
    assert main(["federate", str(tmp_path / "nope.json"), str(tmp_path / "also.json")]) == 2


def test_allen_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["allen", TEMPORAL]) == 0
    out = capsys.readouterr().out
    assert "Allen interval relations" in out and "meets" in out
    assert main(["allen", TEMPORAL, "Acme Corp", "--json"]) == 0
    import json

    assert "relations" in json.loads(capsys.readouterr().out)
    assert main(["allen", "nope-dir", "X"]) == 2


def test_roles_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = _mk_corpus(
        tmp_path,
        "roles",
        "# Case\nA Corp transferred $1 to X.\nA Corp transferred $2 to Y.\n"
        "B Corp transferred $3 to P.\nB Corp transferred $4 to Q.\n",
    )
    assert main(["roles", str(corpus), "A Corp", "-k", "3"]) == 0
    assert "similar structural role" in capsys.readouterr().out
    assert main(["roles", str(corpus), "A Corp", "--json"]) == 0
    import json

    assert json.loads(capsys.readouterr().out)["found"] is True
    assert main(["roles", str(corpus), "Nobody Ltd"]) == 0
    assert "not found" in capsys.readouterr().out
    assert main(["roles", str(tmp_path / "nope"), "X"]) == 2
    # The opt-in node2vec backend degrades to deterministic (with a note) when the extra is absent.
    assert main(["roles", str(corpus), "A Corp", "--backend", "node2vec"]) == 0
    assert "backend:" in capsys.readouterr().out


def test_cache_status_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Cold dir.
    (tmp_path / "graph.json").write_text('{"nodes":[]}', encoding="utf-8")
    assert main(["cache", "status", str(tmp_path)]) == 0
    assert "COLD" in capsys.readouterr().out
    # Warm cache + JSON.
    cache = tmp_path / "llm"
    cache.mkdir()
    (cache / ("a" * 64 + ".json")).write_text('{"response":"x"}', encoding="utf-8")
    assert main(["cache", "status", str(tmp_path), "--json"]) == 0
    import json

    assert json.loads(capsys.readouterr().out)["warm"] is True
    assert main(["cache", "status", str(tmp_path / "nope")]) == 2


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
