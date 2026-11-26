"""Tests for the typo-tolerance evaluation (eval_typos.py) on a small fixture bundle with the fake embedder.

These describe existing behaviour (characterization tests): typo generation, word replacement, the report and its
gates, and the files written. The real numbers come from `make pipeline-eval-typos` on a full bundle.
"""

import json
import random

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline import eval_typos
from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.search import SearchEngine
from looma_pipeline.source import DictSource


@pytest.fixture
def engine(settings):
    result = run_build(settings, "all", source=DictSource(fx.looma_data()), until="f08",
                       counter=WhitespaceCounter(), embedder=FakeEmbedder())
    engine = SearchEngine(result.run_dir / "staging", FakeEmbedder())
    yield engine
    engine.close()


@pytest.mark.parametrize("word, alphabet", [("measurement", eval_typos.ALPHABETS["en"]),
                                            ("प्रकाश", eval_typos.ALPHABETS["np"])])
def test_a_typo_is_one_seeded_edit_away(word, alphabet):
    first = eval_typos.make_typo(word, random.Random(7), alphabet)
    again = eval_typos.make_typo(word, random.Random(7), alphabet)
    assert first == again and first != word
    assert abs(len(first) - len(word)) <= 1


def test_only_the_first_whole_word_is_replaced_keeping_its_case():
    assert eval_typos.replace_word("units Unit unit", "unit", "unti") == "units Unti unit"


def test_the_evaluation_decides_its_gates_and_writes_a_report(settings, engine):
    report = eval_typos.run_typo_eval(settings, engine, "fixture-bundle")
    assert report["bundle"] == "fixture-bundle"
    assert {"T1", "T2", "T3", "T5"} <= set(report["gates"])
    assert all(isinstance(gate["pass"], bool) for gate in report["gates"].values())
    folder = eval_typos.write_report(settings, report)
    assert json.loads((folder / "report.json").read_text(encoding="utf-8"))["bundle"] == "fixture-bundle"
    assert "T1" in (folder / "report.md").read_text(encoding="utf-8") == eval_typos.markdown(report)
