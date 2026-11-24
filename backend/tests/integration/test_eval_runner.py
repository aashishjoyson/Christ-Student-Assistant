"""Evaluation runner: scoring, the real graph wiring, the frozen configuration and the written artefacts. Fakes only; no network."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.core.config import REPO_ROOT
from app.domain.documents import RetrievedChunk
from app.domain.model_modes import PROMPT_VERSIONS
from app.domain.prompts import NO_EVIDENCE_ANSWER
from app.eval.golden import GoldenCase, load_golden
from app.eval.runner import AskFailed, build_summary, index_fingerprint, run_cases, snapshot_config, write_run
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatError
from tests.fakes import FakeChatClient, FakeRetriever

CAL = "calendar.pdf"
CASES = [
    GoldenCase("c1", "When is Deepavali?", True, "calendar", expected_sources=(CAL,), expected_facts=("10 november|november 10",)),
    GoldenCase("c2", "When is Good Friday?", True, "calendar", expected_sources=(CAL,), expected_facts=("26 march|march 26",)),
    GoldenCase("u1", "What is on the menu?", False, "unanswerable", absent_terms=("menu",)),
]
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def chunk(source: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(f"{source}:0", "text", source, source, distance=distance)


def retrieve(question: str, k: int) -> list[RetrievedChunk]:
    if "menu" in question.lower():
        return [chunk("handbook.pdf", 0.71)]
    return [chunk(CAL, 0.31), chunk("handbook.pdf", 0.52)]


def reply(answer: str, intent: str = "academic_qa", cited: bool = True) -> dict:
    return {"answer": answer, "intent": intent, "grounded": True, "handled_by": {"model": "fake-model"},
            "citations": [{"index": 1, "source_name": CAL, "cited": cited}] if cited else [],
            "usage": {"latency_ms": 900, "input_tokens": 100, "output_tokens": 20, "est_cost_usd": 0.0004}}


def good_system(question: str, mode: str) -> dict:
    if "deepavali" in question.lower():
        return reply("It is on 10 November 2026 [1].")
    if "good friday" in question.lower():
        return reply("It is on 26 March 2027 [1].")
    return reply(NO_EVIDENCE_ANSWER, cited=False)


def degraded_system(question: str, mode: str) -> dict:
    """What a broken index looks like: the answers are not found, and an unanswerable question gets an invented answer."""
    if "menu" in question.lower():
        return reply("Today there is biryani.", cited=False)
    return reply(NO_EVIDENCE_ANSWER, cited=False)


def test_a_good_system_scores_well_and_a_degraded_one_visibly_worse() -> None:
    good_rows, good_ret = run_cases(CASES, ["rag"], good_system, retrieve, top_k=4)
    bad_rows, _ = run_cases(CASES, ["rag"], degraded_system, retrieve, top_k=4)
    good = build_summary(good_rows, good_ret, 4, 0.6)["modes"]["rag"]
    bad = build_summary(bad_rows, good_ret, 4, 0.6)["modes"]["rag"]
    assert (good["answer_accuracy"], good["correct_refusal_rate"], good["false_refusal_rate"]) == (1.0, 1.0, 0.0)
    assert (good["citation_hit_rate"], good["retrieval_hit_at_4"], good["retrieval_mrr"], good["routed_academic_rate"]) == (1.0, 1.0, 1.0, 1.0)
    assert (bad["answer_accuracy"], bad["false_refusal_rate"], bad["unsupported_answer_rate"]) == (0.0, 1.0, 1.0)
    assert good["answer_accuracy"] > bad["answer_accuracy"] and good["cost_usd_total"] == 0.0012


def test_the_runner_records_how_many_passages_the_model_was_given_and_the_best_distance() -> None:
    def spread(question: str, k: int) -> list[RetrievedChunk]:
        return [chunk("a.pdf", 0.62), chunk("b.pdf", 0.31), chunk("c.pdf", 0.9)]  # re-ranked order: the closest vector is not first

    rows, retrievals = run_cases(CASES[:1], ["direct", "rag"], good_system, spread, top_k=3, max_distance=0.75)
    by_mode = {r["mode"]: r for r in rows}
    assert by_mode["rag"]["passages_supplied"] == 2 and by_mode["direct"]["passages_supplied"] == 0
    assert retrievals[0]["top1_distance"] == 0.31 and by_mode["rag"]["top1_distance"] == 0.31


def test_the_runner_records_whether_the_proving_quote_reached_the_model() -> None:
    proven = GoldenCase("p", "When is Deepavali?", True, "calendar", expected_sources=(CAL,), expected_facts=("10 november",),
                        evidence=("10 (Tue) Holiday- Balipadyami, Deepavali",))

    def with_text(text: str):  # type: ignore[no-untyped-def]
        return lambda question, k: [RetrievedChunk("c:0", text, CAL, CAL, distance=0.3)]

    # PDF line breaks inside the quote do not matter
    broken_lines = "... 10 (Tue)" + chr(10) + "Holiday- Balipadyami," + chr(10) + "Deepavali ..."
    found, _ = run_cases([proven], ["rag"], good_system, with_text(broken_lines), 4)
    missed, ret = run_cases([proven], ["rag"], good_system, with_text("an unrelated passage"), 4)
    assert found[0]["evidence_in_context"] is True and missed[0]["evidence_in_context"] is False
    assert ret[0]["evidence_in_context"] is False
    unanswerable, _ = run_cases([CASES[2]], ["rag"], good_system, retrieve, 4)
    assert unanswerable[0]["evidence_in_context"] is None


def test_evidence_beyond_the_distance_cut_off_does_not_count_as_reaching_the_model() -> None:
    proven = GoldenCase("p", "When is Deepavali?", True, "calendar", expected_sources=(CAL,), expected_facts=("10 november",),
                        evidence=("Balipadyami",))
    far = lambda question, k: [RetrievedChunk("c:0", "Holiday- Balipadyami, Deepavali", CAL, CAL, distance=0.9)]  # noqa: E731
    withheld, _ = run_cases([proven], ["rag"], good_system, far, 4, max_distance=0.75)
    shown, _ = run_cases([proven], ["rag"], good_system, far, 4, max_distance=None)
    assert withheld[0]["evidence_in_context"] is False and withheld[0]["passages_supplied"] == 0
    assert shown[0]["evidence_in_context"] is True


def test_every_mode_is_run_for_every_case_and_direct_mode_has_no_retrieval_metrics() -> None:
    rows, _ = run_cases(CASES, ["direct", "rag"], good_system, retrieve, top_k=4)
    assert len(rows) == 6 and {r["mode"] for r in rows} == {"direct", "rag"}
    direct = [r for r in rows if r["mode"] == "direct"]
    assert all(r["retrieved_sources"] == [] and r["top1_distance"] is None for r in direct)
    summary = build_summary(rows, [], 4, None)["modes"]
    assert summary["direct"]["retrieval_mrr"] is None and summary["rag"]["retrieval_mrr"] == 1.0


def test_an_error_is_recorded_not_hidden_and_the_run_carries_on() -> None:
    def flaky(question: str, mode: str) -> dict:
        if mode == "rag_peft":
            raise AskFailed("model3_not_configured")
        return good_system(question, mode)

    rows, _ = run_cases(CASES, ["rag", "rag_peft"], flaky, retrieve, top_k=4)
    peft = [r for r in rows if r["mode"] == "rag_peft"]
    assert all(r["error_code"] == "model3_not_configured" and r["answer"] == "" for r in peft)
    summary = build_summary(rows, [], 4, None)["modes"]
    assert summary["rag_peft"]["errors"] == 3 and summary["rag_peft"]["latency_p50_ms"] is None and summary["rag"]["errors"] == 0


def test_the_real_graph_is_driven_end_to_end_and_model3_never_falls_back(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(
        primary=FakeChatClient(reply="It is on 10 November 2026 [1]."),
        retriever=FakeRetriever([chunk(CAL, 0.3), chunk("handbook.pdf", 0.5)]),
    )

    def ask(question: str, mode: str) -> dict:
        try:
            return env.container.chat_service.handle(ChatRequest(message=question, model_mode=mode), None).model_dump(mode="json")  # type: ignore[arg-type]
        except ChatError as exc:
            raise AskFailed(exc.code, str(exc)) from exc

    rows, retrievals = run_cases(CASES[:1], ["direct", "rag", "rag_peft"], ask, env.retriever.retrieve, top_k=4)
    by_mode = {r["mode"]: r for r in rows}
    rag = by_mode["rag"]
    assert rag["answered_correctly"] and rag["citation_hit"] and rag["intent"] == "academic_qa" and rag["input_tokens"] == 120
    assert rag["model"] == "fake-model" and rag["latency_ms"] is not None and retrievals[0]["top1_distance"] == 0.3
    assert by_mode["direct"]["rag"] is False and not by_mode["direct"]["citation_hit"]
    assert by_mode["rag_peft"]["error_code"] == "model3_not_configured" and by_mode["rag_peft"]["answer"] == ""  # no silent substitute


def test_the_frozen_config_names_everything_that_changes_an_answer_and_no_secret(make_env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    env = make_env()
    golden = REPO_ROOT / "data" / "eval" / "academic_real.jsonl"
    cases = load_golden(golden)
    index = index_fingerprint([
        {"source": "drive", "name": "b.pdf", "status": "indexed", "chunk_count": 5, "content_sha256": "bb"},
        {"source": "drive", "name": "a.pdf", "status": "indexed", "chunk_count": 3, "content_sha256": "aa"},
        {"source": "drive", "name": "old.pdf", "status": "deleted", "chunk_count": 0, "content_sha256": "cc"},
    ], 8)
    versions = {m.value: v for m, v in PROMPT_VERSIONS.items()}
    git = {"commit": "abc123", "dirty": False}

    config = snapshot_config(env.settings, versions, golden, cases, ["direct", "rag"], index, git, now=NOW)
    text = json.dumps(config)
    assert "test-key-not-real" not in text and "test-admin-key" not in text and env.settings.app_secret_key.get_secret_value() not in text
    assert config["prompt_versions"]["rag"] == PROMPT_VERSIONS[next(m for m in PROMPT_VERSIONS if m.value == "rag")]
    assert config["retrieval"]["top_k"] == env.settings.rag_top_k and config["golden_set"]["cases"] == len(cases)
    assert len(config["golden_set"]["sha256"]) == 64 and config["git"]["commit"] == "abc123"
    assert [f["name"] for f in config["index"]["files"]] == ["a.pdf", "b.pdf"]  # sorted; the deleted file is not part of the index

    same = snapshot_config(env.settings, versions, golden, cases, ["direct", "rag"], index, git, now=NOW)
    assert same["run_id"] == config["run_id"] and config["run_id"].startswith("eval-20261124-120000-")
    different_setting = env.settings.model_copy(update={"rag_top_k": env.settings.rag_top_k + 1})
    assert snapshot_config(different_setting, versions, golden, cases, ["direct", "rag"], index, git, now=NOW)["run_id"] != config["run_id"]
    changed_index = index_fingerprint([{"source": "drive", "name": "a.pdf", "status": "indexed", "chunk_count": 3, "content_sha256": "zz"}], 3)
    assert snapshot_config(env.settings, versions, golden, cases, ["direct", "rag"], changed_index, git, now=NOW)["run_id"] != config["run_id"]


def test_a_run_writes_its_artefacts(tmp_path: Path) -> None:
    rows, retrievals = run_cases(CASES, ["rag"], good_system, retrieve, top_k=4)
    summary = build_summary(rows, retrievals, 4, 0.6)
    config = {"run_id": "eval-test", "created_at": NOW.isoformat()}
    paths = write_run(tmp_path / "eval-test", config, rows, retrievals, summary)
    assert {p.name for p in paths.values()} == {"config.json", "summary.json", "results.jsonl", "results.csv", "retrieval.jsonl"}
    assert all(p.is_file() for p in paths.values())
    saved = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert saved["run_id"] == "eval-test" and saved["modes"]["rag"]["n"] == 3 and saved["calibration"]["status"] == "ok"
    assert len(paths["results"].read_text(encoding="utf-8").strip().splitlines()) == 3
    with paths["results_csv"].open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 3 and {"mode", "case_id", "answered_correctly", "latency_ms"} <= set(csv_rows[0])


def test_the_distance_cut_off_is_calibrated_from_the_retrieval_of_answerable_and_unanswerable_questions() -> None:
    _, retrievals = run_cases(CASES, [], good_system, retrieve, top_k=4)
    calibration = build_summary([], retrievals, 4, 0.6)["calibration"]
    assert calibration["status"] == "ok" and 0.31 < calibration["recommended_max_distance"] < 0.71
    assert calibration["balanced_accuracy_at_recommended"] == 1.0 and not calibration["groups_overlap"]


def test_settings_object_is_not_needed_by_the_core() -> None:
    """run_cases and build_summary only need plain functions: the CLI is the only place that touches settings and the container."""
    stub = SimpleNamespace(source_name="x.pdf", text="nothing relevant", distance=0.1)
    rows, _ = run_cases(CASES[:1], ["rag"], good_system, lambda q, k: [stub], top_k=4)
    assert rows[0]["retrieved_sources"] == ["x.pdf"] and rows[0]["retrieval_rank"] is None  # right words, wrong document
