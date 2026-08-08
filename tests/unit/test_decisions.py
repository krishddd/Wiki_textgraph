"""Decision objects — derivation, causal edges, and PROV-O export."""

import json
from pathlib import Path

import pytest
from textgraph.cli import main
from textgraph.core.config import Config
from textgraph.l1_structure.decisions import derive_decisions
from textgraph.l9_artifacts.prov import export_prov_bytes
from textgraph.pipeline import build

ADR = Path(__file__).parent.parent / "fixtures" / "corpora" / "adr"


def _decisions(nodes: list) -> list:
    return [n for n in nodes if "Decision" in n.labels]


def _build_cross_ref(tmp_path: Path) -> object:
    """Two ADRs where the newer one explicitly supersedes the older."""
    (tmp_path / "a.md").write_text(
        "# ADR-0005: Base retention\n\nWHY: Keep evidence for audit.\n", encoding="utf-8"
    )
    (tmp_path / "b.md").write_text(
        "# ADR-0009: Stronger retention\n\n"
        "DECISION: This SUPERSEDES ADR-0005 to require byte-range citations.\n",
        encoding="utf-8",
    )
    return build(tmp_path)


# --- derivation --------------------------------------------------------------


def test_decisions_derived_from_adr_fixture() -> None:
    r = build(ADR)
    decs = _decisions(r.nodes)
    cats = sorted(n.properties["category"] for n in decs)
    # Two ADR records + two WHY lines + one DECISION line across the two files.
    assert cats == ["adr", "adr", "decision", "why", "why"]
    assert r.graph_stats["decisions"] == len(decs) == 5
    # Every Decision is provenanced back to its rationale.
    derived = [e for e in r.edges if e.predicate == "DERIVED_FROM"]
    assert len(derived) == len(decs)
    assert all(e.source_spans for e in derived)  # cited (re-verified by the provenance gate)


def test_non_decision_markers_are_not_promoted() -> None:
    r = build(ADR)
    # NOTE/TODO/CONTEXT/CONSEQUENCES markers must never become Decision nodes.
    assert all(n.properties["category"] in {"adr", "why", "decision"} for n in _decisions(r.nodes))


def test_mid_line_adr_reference_is_not_a_record(tmp_path: Path) -> None:
    r = _build_cross_ref(tmp_path)
    decs = _decisions(r.nodes)
    # Only the two heading ADRs are 'adr' records; the "SUPERSEDES ADR-0005" mention
    # inside the DECISION line must NOT create a third phantom 'adr' decision.
    assert sorted(n.properties["category"] for n in decs) == ["adr", "adr", "decision", "why"]


def test_derivation_is_deterministic() -> None:
    r = build(ADR)
    first = derive_decisions(r.nodes, r.edges)
    second = derive_decisions(r.nodes, r.edges)
    assert [n.node_id for n in first[0]] == [n.node_id for n in second[0]]
    assert [e.edge_id for e in first[1]] == [e.edge_id for e in second[1]]


def test_decisions_off_by_config(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# ADR-0001: X\n\nDECISION: do the thing.\n", encoding="utf-8")
    r = build(tmp_path, config=Config(derive_decisions=False))
    assert _decisions(r.nodes) == []
    assert r.graph_stats["decisions"] == 0


# --- causal edges ------------------------------------------------------------


def test_supersedes_produces_precedent_for_edge(tmp_path: Path) -> None:
    r = _build_cross_ref(tmp_path)
    by_id = {n.node_id: n for n in r.nodes}
    causal = [e for e in r.edges if e.predicate in {"CAUSED", "INFLUENCED", "PRECEDENT_FOR"}]
    assert len(causal) == 1
    e = causal[0]
    assert e.predicate == "PRECEDENT_FOR"
    # The referenced (older) ADR-0005 record is the source; the new DECISION is the object.
    assert by_id[e.subject].properties["category"] == "adr"
    assert "ADR-0005" in by_id[e.subject].properties["marker"]
    assert by_id[e.object].properties["category"] == "decision"
    assert str(e.tag) == "INFERRED" and e.source_spans  # cited, non-GENERATED


def test_caused_by_keyword_maps_to_caused(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# ADR-0002: Root cause\n\nWHY: baseline.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text(
        "# ADR-0003: Follow-up\n\nDECISION: Introduced BECAUSE OF ADR-0002 findings.\n",
        encoding="utf-8",
    )
    r = build(tmp_path)
    causal = [e for e in r.edges if e.predicate in {"CAUSED", "INFLUENCED", "PRECEDENT_FOR"}]
    assert [e.predicate for e in causal] == ["CAUSED"]


def test_bare_reference_maps_to_influenced(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# ADR-0004: Context\n\nWHY: baseline.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text(
        "# ADR-0006: Extension\n\nDECISION: See ADR-0004 for related context.\n",
        encoding="utf-8",
    )
    r = build(tmp_path)
    causal = [e for e in r.edges if e.predicate in {"CAUSED", "INFLUENCED", "PRECEDENT_FOR"}]
    assert [e.predicate for e in causal] == ["INFLUENCED"]


# --- PROV-O export -----------------------------------------------------------


def test_prov_export_is_valid_jsonld() -> None:
    r = build(ADR)
    body = export_prov_bytes(r.nodes, r.edges)
    assert body.endswith(b"\n")
    doc = json.loads(body)
    assert doc["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    graph = doc["@graph"]
    types = {json.dumps(o["@type"]) for o in graph}
    assert '"prov:Activity"' in types  # decisions
    assert '"prov:Entity"' in types  # source documents
    agents = [o for o in graph if o["@id"] == "textgraph:extractor"]
    assert len(agents) == 1 and "prov:SoftwareAgent" in agents[0]["@type"]
    # Every activity carries a re-verifiable byte-range citation.
    activities = [o for o in graph if o.get("@type") == "prov:Activity"]
    assert activities and all("textgraph:sourceSpan" in a for a in activities)


def test_prov_export_is_deterministic() -> None:
    r = build(ADR)
    assert export_prov_bytes(r.nodes, r.edges) == export_prov_bytes(r.nodes, r.edges)


def test_prov_causal_becomes_was_informed_by(tmp_path: Path) -> None:
    r = _build_cross_ref(tmp_path)
    doc = json.loads(export_prov_bytes(r.nodes, r.edges))
    informed = [o for o in doc["@graph"] if o.get("wasInformedBy")]
    assert len(informed) == 1  # the new decision was informed by the superseded ADR
    effect = informed[0]
    assert effect["wasInformedBy"][0].startswith("textgraph:decision:")
    assert effect["textgraph:causedBy"][0]["relation"] == "PRECEDENT_FOR"


# --- CLI ---------------------------------------------------------------------


def test_export_cli_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export", str(ADR), "--format", "prov-o"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert "@graph" in doc and doc["@context"]["textgraph"]


def test_export_cli_to_file(tmp_path: Path) -> None:
    out = tmp_path / "prov.jsonld"
    assert main(["export", str(ADR), "-o", str(out)]) == 0
    assert out.read_bytes().endswith(b"\n")
    assert json.loads(out.read_text(encoding="utf-8"))["@graph"]


def test_export_cli_missing_path_errors(tmp_path: Path) -> None:
    assert main(["export", str(tmp_path / "nope")]) == 2
