"""L9 — Artifacts & Skill Surface.

Emits the byte-stable graph.json contract plus GRAPH_REPORT.md, graph.html,
schema.yaml, and manifest.json. See ARCHITECTURE.md.
"""

from textgraph.l9_artifacts.artifacts import ArtifactPaths, write_artifacts

__all__ = ["ArtifactPaths", "write_artifacts"]
