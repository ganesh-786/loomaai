import json

import looma_fixture as fx
from fake_embedder import FakeEmbedder

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.e2e import run_e2e
from looma_pipeline.pipeline import run_build
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f09_suggestions


def test_suggestions_are_proposals_with_provenance_and_skip_linked_items(settings, monkeypatch):
    monkeypatch.setattr(f09_suggestions, "MIN_SIMILARITY", 0.0)  # structure test; the real threshold is uncalibrated
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f09",
                       counter=WhitespaceCounter(), embedder=FakeEmbedder())
    proposals = result.outputs["proposals"]
    assert proposals
    items = result.outputs["items"]
    for row in proposals:
        assert row["status"] == "proposed" and row["run_id"] == result.run_id
        assert row["model"] == "fake-model@1" and row["snapshot_hash"]
        assert items[row["activity_id"]].ft != "chapter"
        assert row["ch_id"] not in items[row["activity_id"]].ch_ids  # already linked items are never proposed
    report = json.loads((result.run_dir / "f09_suggestions.json").read_text())
    assert report["details"]["written_to_mongodb"] is False
    assert len((result.run_dir / "proposals.jsonl").read_text().splitlines()) == len(proposals)


def test_end_to_end_decides_every_gate(settings, fake_model_dir):
    report = run_e2e(settings, "pilot", source=DictSource(fx.looma_data()), counter=WhitespaceCounter(),
                     embedder=FakeEmbedder(), model_dir=fake_model_dir, with_tests=False)
    gates = report["gates"]
    assert all(gates[g]["pass"] for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7")), gates
    assert gates["G8"]["pass"] is None and gates["G9"]["pass"] is None and gates["G10"]["pass"] is None
    assert "checksums" in gates["G3"]["evidence"] and "model expected by the reader" in gates["G3"]["evidence"]
    assert len(report["bundles"]) == 2
