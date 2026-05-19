from __future__ import annotations

import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path("REPO_ROOT_PLACEHOLDER/backend/scripts")
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))

from services.translation.memory import JobMemory
from services.translation.memory import JobMemoryStore
from services.translation.memory import update_job_memory_from_batch
from services.translation.memory.candidates import extract_scored_term_candidates


def test_job_memory_extracts_translated_term_pairs_and_prompt_summary(tmp_path) -> None:
    memory = JobMemory.empty(tmp_path / "job-memory.json")
    batch = [
        {
            "item_id": "p001-b001",
            "source_text": "Color centers are also called F-centers.",
            "protected_source_text": "Color centers are also called F-centers.",
        }
    ]
    translated = {
        "p001-b001": {
            "translated_text": "色心（F-centers）也被称为F心。",
        }
    }

    changed = update_job_memory_from_batch(memory, batch=batch, translated=translated)

    assert changed >= 1
    assert memory.terms["F-centers"]["value"] == "色心"
    assert "F-centers => 色心" in memory.prompt_summary()


def test_job_memory_preserve_hint_for_command_like_blocks(tmp_path) -> None:
    memory = JobMemory.empty(tmp_path / "job-memory.json")
    batch = [
        {
            "item_id": "p002-b003",
            "source_text": "$ uv venv deeph --python=3.13\n$ source deeph/bin/activate",
            "protected_source_text": "$ uv venv deeph --python=3.13\n$ source deeph/bin/activate",
        }
    ]
    translated = {
        "p002-b003": {
            "translated_text": "$ uv venv deeph --python=3.13\n$ source deeph/bin/activate",
        }
    }

    changed = update_job_memory_from_batch(memory, batch=batch, translated=translated)

    assert changed == 1
    summary = memory.prompt_summary()
    assert "技术原文/代码/参数块" in summary
    assert "$ uv venv deeph" in summary


def test_job_memory_store_persists_json(tmp_path) -> None:
    store = JobMemoryStore(tmp_path / "translated" / "job-memory.json")
    batch = [
        {
            "item_id": "p001-b001",
            "source_text": "Self-consistent field (SCF) iterations.",
            "protected_source_text": "Self-consistent field (SCF) iterations.",
        }
    ]
    translated = {
        "p001-b001": {
            "translated_text": "自洽场（SCF）迭代。",
        }
    }

    assert store.update_from_batch(batch, translated) >= 1
    assert "SCF => 自洽场" in store.summary()


def test_job_memory_prompt_summary_filters_sentence_fragments(tmp_path) -> None:
    memory = JobMemory.empty(tmp_path / "job-memory.json")
    memory.add_term(key="DFTB", value="密度泛函紧束缚", source="p001-b001")
    memory.add_term(key="BJ", value="相应的体系已从DFTB3-D3", source="p001-b002")
    memory.add_term(key="GFN2-xTB", value="GFN2-xTB", source="p001-b003")

    summary = memory.prompt_summary()

    assert "DFTB => 密度泛函紧束缚" in summary
    assert "GFN2-xTB => GFN2-xTB" in summary
    assert "BJ =>" not in summary


def test_job_memory_prompt_summary_for_source_only_returns_relevant_terms(tmp_path) -> None:
    memory = JobMemory.empty(tmp_path / "job-memory.json")
    memory.add_term(key="SCF", value="自洽场", source="p001-b001")
    memory.add_term(key="DFTB", value="密度泛函紧束缚", source="p001-b002")
    memory.add_term(key="CAMM", value="累积原子多极矩", source="p001-b003")

    summary = memory.prompt_summary_for_source("The SCF procedure computes molecular orbitals.")

    assert "SCF => 自洽场" in summary
    assert "DFTB =>" not in summary
    assert "CAMM =>" not in summary


def test_job_memory_store_summary_for_batch_only_returns_relevant_terms(tmp_path) -> None:
    store = JobMemoryStore(tmp_path / "translated" / "job-memory.json")
    memory = JobMemory.empty(store.path)
    memory.add_term(key="SCF", value="自洽场", source="p001-b001")
    memory.add_term(key="DFTB", value="密度泛函紧束缚", source="p001-b002")
    store.save(memory)

    summary = store.summary_for_batch(
        [
            {
                "item_id": "p010-b004",
                "source_text": "This paragraph discusses DFTB approximations.",
            }
        ]
    )

    assert "DFTB => 密度泛函紧束缚" in summary
    assert "SCF =>" not in summary


def test_term_candidate_extraction_exposes_scores_without_breaking_tuple_api() -> None:
    candidates = extract_scored_term_candidates(
        "Color centers are also called F-centers.",
        "色心（F-centers）也被称为 F-centers。",
    )

    assert candidates
    explicit = candidates[0]
    assert explicit.key == "F-centers"
    assert explicit.value == "色心"
    assert explicit.source == "explicit_pair"
    assert explicit.score >= 1.0
