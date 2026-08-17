"""Cross-graph federation — multi-case entity linking over content-addressed ids."""

from pathlib import Path

from textgraph.l8_retrieval.federation import (
    CaseGraph,
    entity_dossier,
    load_federation,
    shared_entities,
)
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.pipeline import build


def _write_case(tmp_path: Path, name: str, text: str) -> Path:
    src = tmp_path / f"{name}-src"
    src.mkdir()
    (src / "f.md").write_text(text, encoding="utf-8")
    r = build(src)
    out = tmp_path / f"{name}.json"
    out.write_bytes(
        dump_graph_bytes(
            build_graph_document(
                config_hash=r.config_hash, results=r.results, nodes=r.nodes, edges=r.edges
            )
        )
    )
    return out


def _case(tmp_path: Path, name: str, text: str) -> CaseGraph:
    src = tmp_path / f"{name}-src"
    src.mkdir()
    (src / "f.md").write_text(text, encoding="utf-8")
    r = build(src)
    return CaseGraph(name=name, nodes=r.nodes, edges=r.edges)


def test_shared_entities_link_cases_by_content_addressed_id(tmp_path: Path) -> None:
    # Acme Corp appears in both cases -> a cross-case link, found by identical node_id (no
    # fuzzy matching). Zeta (only in case 2) does not.
    c1 = _case(tmp_path, "4471", "# 4471\nAcme Corp transferred $1,000 to Beta Ltd.\n")
    c2 = _case(tmp_path, "4490", "# 4490\nAcme Corp controls Zeta Holdings.\n")
    shared = shared_entities([c1, c2])
    names = {s.name for s in shared}
    assert "Acme Corp" in names
    assert "Zeta Holdings" not in names  # single-case entity is not a bridge
    acme = next(s for s in shared if s.name == "Acme Corp")
    assert sorted(acme.cases) == ["4471", "4490"]
    assert acme.degree["4471"] >= 1 and acme.degree["4490"] >= 1


def test_min_cases_threshold(tmp_path: Path) -> None:
    c1 = _case(tmp_path, "a", "# a\nAcme Corp controls Beta Ltd.\n")
    c2 = _case(tmp_path, "b", "# b\nAcme Corp controls Gamma Inc.\n")
    c3 = _case(tmp_path, "c", "# c\nDelta LLC controls Omega Bank.\n")
    # Acme spans 2 of 3; nothing spans all 3.
    assert {s.name for s in shared_entities([c1, c2, c3], min_cases=2)} == {"Acme Corp"}
    assert shared_entities([c1, c2, c3], min_cases=3) == []


def test_entity_dossier_across_cases(tmp_path: Path) -> None:
    c1 = _case(tmp_path, "4471", "# 4471\nJohn Doe is director of Acme Corp.\n")
    c2 = _case(tmp_path, "4490", "# 4490\nJohn Doe transferred $500 to Delta Trust.\n")
    dossier = entity_dossier([c1, c2], "John Doe")
    assert dossier["found"]
    assert sorted(dossier["in_cases"]) == ["4471", "4490"]
    preds = {r["predicate"] for c in dossier["cases"] for r in c["relations"]}
    assert "DIRECTOR_OF" in preds and "TRANSFERRED" in preds


def test_entity_dossier_missing_entity(tmp_path: Path) -> None:
    c1 = _case(tmp_path, "a", "# a\nAcme Corp controls Beta Ltd.\n")
    dossier = entity_dossier([c1], "Nonexistent Ltd")
    assert dossier["found"] is False
    assert dossier["in_cases"] == []


def test_load_federation_names_cases_by_folder_when_file_is_graph_json(tmp_path: Path) -> None:
    # Two files both named graph.json (the common case) must not collide to one name.
    d1 = tmp_path / "caseA"
    d2 = tmp_path / "caseB"
    for d, text in (
        (d1, "# A\nAcme Corp controls Beta Ltd.\n"),
        (d2, "# B\nAcme Corp controls X.\n"),
    ):
        d.mkdir()
        src = d / "src"
        src.mkdir()
        (src / "f.md").write_text(text, encoding="utf-8")
        r = build(src)
        (d / "graph.json").write_bytes(
            dump_graph_bytes(
                build_graph_document(
                    config_hash=r.config_hash, results=r.results, nodes=r.nodes, edges=r.edges
                )
            )
        )
    cases = load_federation([d1 / "graph.json", d2 / "graph.json"])
    assert {c.name for c in cases} == {"caseA", "caseB"}  # named by folder, not "graph"


def test_load_federation_missing_graph_json(tmp_path: Path) -> None:
    import pytest

    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        load_federation([tmp_path / "empty"])


def test_federation_is_deterministic(tmp_path: Path) -> None:
    # A file-based round-trip: loading + federating twice gives identical results.
    p1 = _write_case(tmp_path, "one", "# one\nAcme Corp transferred $1 to Beta Ltd.\n")
    p2 = _write_case(tmp_path, "two", "# two\nAcme Corp controls Beta Ltd.\n")
    a = [s.to_dict() for s in shared_entities(load_federation([p1, p2]))]
    b = [s.to_dict() for s in shared_entities(load_federation([p1, p2]))]
    assert a == b
    assert any(s["name"] == "Acme Corp" for s in a)
