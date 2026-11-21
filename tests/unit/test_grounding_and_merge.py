from __future__ import annotations

import json

from diffguard.context import ContextChunk, pack_context_budget
from diffguard.diff import parse_unified_diff
from diffguard.domain import (
    Category,
    CodeSnapshot,
    ContextPolicy,
    DiffSide,
    EvidenceStatus,
    FilterStatus,
    FindingCandidate,
    FindingKind,
    InputSource,
    ReviewPolicy,
    Severity,
    SourceType,
)
from diffguard.llm import (
    LLMCandidateItem,
    LLMVerifyDecision,
    LLMVerifyOutput,
    RateLimitedRouter,
    ReplayProvider,
)
from diffguard.pipeline import (
    CandidateEnvelope,
    DeterministicGroundingGate,
    SelectiveVerificationFilter,
    SemanticMerger,
    llm_items_to_envelopes,
)

SAMPLE_DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,4 +1,6 @@
 import sqlite3
 
 def get_user(conn, name):
-    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchall()
+    query = f"SELECT * FROM users WHERE name = '{name}'"
+    eval(name)
+    return conn.execute(query).fetchall()
"""

BASE_SRC = (
    "import sqlite3\n\n"
    "def get_user(conn, name):\n"
    '    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchall()\n'
)

HEAD_SRC = (
    "import sqlite3\n\n"
    "def get_user(conn, name):\n"
    "    query = f\"SELECT * FROM users WHERE name = '{name}'\"\n"
    "    eval(name)\n"
    "    return conn.execute(query).fetchall()\n"
)


def _snapshot_and_parsed() -> tuple[CodeSnapshot, list]:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    snapshot = CodeSnapshot(
        repo_full_name="local/demo",
        input_source=InputSource.CLI_CUC_BO,
        base_commit_sha="0" * 40,
        head_commit_sha="1" * 40,
        merge_base_sha="0" * 40,
        diff_hash="2" * 64,
        total_files=1,
        total_additions=3,
        total_deletions=1,
        files=[parsed[0].to_domain(old_line_count=4, new_line_count=6)],
    )
    return snapshot, parsed


def test_grounding_gate_rejects_hallucinations_and_keeps_grounded_finding() -> None:
    snapshot, parsed = _snapshot_and_parsed()
    items = [
        LLMCandidateItem(
            file_path="app.py",
            diff_side=DiffSide.RIGHT,
            start_line=4,
            end_line=6,
            category=Category.BAO_MAT,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.CAO,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="SQL injection in get_user()",
            explanation="Interpolating name into query inside `get_user()` causes SQL injection.",
            code_evidence="query = f\"SELECT * FROM users WHERE name = '{name}'\"",
        ),
        LLMCandidateItem(
            file_path="ghost.py",
            diff_side=DiffSide.RIGHT,
            start_line=1,
            end_line=1,
            category=Category.BAO_MAT,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.THAP,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Non-existent file bug",
            explanation="Invented file",
            code_evidence="x = 1",
        ),
        LLMCandidateItem(
            file_path="app.py",
            diff_side=DiffSide.RIGHT,
            start_line=99,
            end_line=99,
            category=Category.CHUC_NANG,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.THAP,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Out of bounds line",
            explanation="Line does not exist",
            code_evidence="return None",
        ),
        LLMCandidateItem(
            file_path="app.py",
            diff_side=DiffSide.LEFT,
            start_line=2,
            end_line=4,
            category=Category.BAO_MAT,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.TRUNG_BINH,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Wrong snippet on LEFT",
            explanation="Hallucinated snippet",
            code_evidence="os.system(name)",
        ),
        LLMCandidateItem(
            file_path="app.py",
            diff_side=DiffSide.RIGHT,
            start_line=4,
            end_line=5,
            category=Category.CHUC_NANG,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.TRUNG_BINH,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Missing AST symbol",
            explanation="Calls `nonexistent_validator_fn()` before execute.",
            code_evidence="eval(name)",
        ),
    ]
    envelopes, invalid_orders = llm_items_to_envelopes(items, invocation_attempt=1)
    gate = DeterministicGroundingGate()
    res = gate.verify(
        envelopes=envelopes,
        snapshot=snapshot,
        parsed_files=parsed,
        base_contents={"app.py": BASE_SRC},
        head_contents={"app.py": HEAD_SRC},
        invalid_order_indices=invalid_orders,
    )

    assert len(res.kept) == 1
    assert res.kept[0].candidate.title == "SQL injection in get_user()"
    assert res.kept[0].hunk_index == 1
    assert len(res.unmapped_rejections) == 1
    reasons = {r.filter_reason: r.filter_status for r in res.rejected}
    assert reasons["line_out_of_file_bounds"] == FilterStatus.LOAI_SAI_DONG
    assert reasons["code_evidence_mismatch"] == FilterStatus.LOAI_THIEU_CAN_CU
    assert reasons["unknown_ast_symbol:nonexistent_validator_fn"] == FilterStatus.LOAI_THIEU_CAN_CU


def test_selective_verification_filter_and_ablation_toggle() -> None:
    snapshot, parsed = _snapshot_and_parsed()
    bundle = pack_context_budget(
        parsed_files=parsed,
        base_contents={"app.py": BASE_SRC},
        head_contents={"app.py": HEAD_SRC},
        context_policy=ContextPolicy.DIFF_AST,
        policy=ReviewPolicy(),
    )
    envelopes = [
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.BANDIT,
                diff_side=DiffSide.RIGHT,
                start_line=4,
                end_line=6,
                category=Category.BAO_MAT,
                severity=Severity.CAO,
                title="SQL injection",
                raw_message="Possible SQL injection",
                code_evidence="conn.execute(query)",
                rule_code="B608",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
        ),
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.RUFF,
                diff_side=DiffSide.RIGHT,
                start_line=1,
                end_line=1,
                category=Category.BAO_TRI,
                severity=Severity.THAP,
                title="Unused import false positive",
                raw_message="sqlite3 unused",
                code_evidence="import sqlite3",
                rule_code="F401",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
        ),
    ]

    ablation = SelectiveVerificationFilter(router=None, enabled=False)
    res_off = ablation.filter(envelopes, bundle)
    assert len(res_off.kept) == 2
    assert len(res_off.invocations) == 0

    verify_json = LLMVerifyOutput(
        decisions=[
            LLMVerifyDecision(candidate_index=0, verdict="NEEDS_VERIFICATION", reason="Caller unknown"),
            LLMVerifyDecision(candidate_index=1, verdict="DROP", reason="sqlite3 is used on line 6"),
        ]
    ).model_dump_json()
    provider = ReplayProvider(queued_responses=[verify_json])
    router = RateLimitedRouter(provider=provider, sleep_fn=lambda _: None)
    verifier = SelectiveVerificationFilter(router=router, enabled=True, model_name="replay-v1")
    res_on = verifier.filter(envelopes, bundle)

    assert len(res_on.invocations) == 1
    assert len(res_on.kept) == 1
    assert res_on.kept[0].evidence_status == EvidenceStatus.CAN_XAC_MINH
    assert len(res_on.rejected) == 1
    assert res_on.rejected[0].filter_status == FilterStatus.LOAI_THIEU_CAN_CU
    assert isinstance(bundle.chunks[0], ContextChunk)
    assert len(json.loads(provider.calls[0][2].split("<candidates>")[1].split("</candidates>")[0])) == 2


def test_semantic_merger_combines_same_bug_and_separates_distinct_same_line_bugs() -> None:
    bandit_sqli = CandidateEnvelope(
        candidate=FindingCandidate(
            file_path="app.py",
            source_type=SourceType.BANDIT,
            diff_side=DiffSide.RIGHT,
            start_line=6,
            end_line=6,
            category=Category.BAO_MAT,
            severity=Severity.TRUNG_BINH,
            title="B608 hardcoded SQL expression",
            raw_message="Possible SQL injection vector through string-based query construction.",
            code_evidence="return conn.execute(query).fetchall()",
            rule_code="B608",
        ),
        evidence_status=EvidenceStatus.CO_CAN_CU,
        hunk_index=1,
    )
    llm_sqli = CandidateEnvelope(
        candidate=FindingCandidate(
            file_path="app.py",
            source_type=SourceType.LLM,
            diff_side=DiffSide.RIGHT,
            start_line=4,
            end_line=6,
            category=Category.BAO_MAT,
            severity=Severity.CAO,
            title="SQL injection via formatted query",
            raw_message="User parameter name is interpolated into SQL string before execute().",
            code_evidence="query = f\"SELECT * FROM users WHERE name = '{name}'\"",
            suggested_fix='conn.execute("SELECT * FROM users WHERE name = ?", (name,))',
            invocation_attempt=1,
        ),
        evidence_status=EvidenceStatus.CO_CAN_CU,
        hunk_index=1,
    )
    distinct_eval = CandidateEnvelope(
        candidate=FindingCandidate(
            file_path="app.py",
            source_type=SourceType.BANDIT,
            diff_side=DiffSide.RIGHT,
            start_line=5,
            end_line=5,
            category=Category.BAO_MAT,
            severity=Severity.CAO,
            title="B307 eval injection",
            raw_message="Use of possibly insecure function eval() allows arbitrary code execution.",
            code_evidence="eval(name)",
            rule_code="B307",
        ),
        evidence_status=EvidenceStatus.CO_CAN_CU,
        hunk_index=1,
    )

    merged = SemanticMerger().merge([bandit_sqli, llm_sqli, distinct_eval])
    assert len(merged.findings) == 2

    sqli_finding = next(f for f in merged.findings if "SQL" in f.title)
    eval_finding = next(f for f in merged.findings if "eval" in f.title.lower())
    assert set(sqli_finding.sources) == {SourceType.BANDIT, SourceType.LLM}
    assert sqli_finding.severity == Severity.CAO
    assert sqli_finding.suggested_fix is not None
    assert eval_finding.sources == [SourceType.BANDIT]
    assert sqli_finding.issue_fingerprint != eval_finding.issue_fingerprint

    kept_cands = [c for c in merged.updated_candidates if c.filter_status == FilterStatus.GIU_LAI]
    dup_cands = [c for c in merged.updated_candidates if c.filter_status == FilterStatus.LOAI_TRUNG]
    assert len(kept_cands) == 2
    assert len(dup_cands) == 1
    assert dup_cands[0].merged_fingerprint == sqli_finding.issue_fingerprint


def test_grounding_gate_edge_cases_order_remediation_rename_and_hunk_scope() -> None:
    rename_diff = """diff --git a/old_mod.py b/new_mod.py
similarity index 80%
rename from old_mod.py
rename to new_mod.py
--- a/old_mod.py
+++ b/new_mod.py
@@ -1,4 +1,5 @@
 def untouched_header():
     return 1
+
 def run_cmd(arg):
-    return old_unsafe(arg)
+    return shlex_candidate(arg)
"""
    long_base = "def untouched_header():\n    return 1\ndef run_cmd(arg):\n    return old_unsafe(arg)\n"
    long_head_lines = [
        "def untouched_header():",
        "    return 1",
        "",
        "def run_cmd(arg):",
        "    return shlex_candidate(arg)",
    ] + [f"val_{i} = {i}" for i in range(15)]
    long_head = "\n".join(long_head_lines) + "\n"

    parsed = parse_unified_diff(rename_diff)
    snapshot = CodeSnapshot(
        repo_full_name="local/demo",
        input_source=InputSource.CLI_CUC_BO,
        base_commit_sha="0" * 40,
        head_commit_sha="1" * 40,
        merge_base_sha="0" * 40,
        diff_hash="3" * 64,
        total_files=1,
        total_additions=2,
        total_deletions=1,
        files=[parsed[0].to_domain(old_line_count=4, new_line_count=len(long_head_lines))],
    )

    items = [
        LLMCandidateItem(
            file_path="new_mod.py",
            diff_side=DiffSide.RIGHT,
            start_line=5,
            end_line=3,
            category=Category.CHUC_NANG,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.THAP,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Reversed line bounds",
            explanation="Reversed bounds check",
            code_evidence="return shlex_candidate(arg)",
        ),
        LLMCandidateItem(
            file_path="new_mod.py",
            diff_side=DiffSide.RIGHT,
            start_line=4,
            end_line=5,
            category=Category.BAO_MAT,
            finding_kind=FindingKind.LOI_TIEM_AN,
            severity=Severity.TRUNG_BINH,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Unescaped command argument",
            explanation="Untrusted arg in `run_cmd()`; use `shlex.quote()` or `subprocess.run()` safely.",
            code_evidence="return shlex_candidate(arg)",
        ),
        LLMCandidateItem(
            file_path="old_mod.py",
            diff_side=DiffSide.LEFT,
            start_line=4,
            end_line=4,
            category=Category.CHUC_NANG,
            finding_kind=FindingKind.GOI_Y_TOI_UU,
            severity=Severity.THAP,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Removed legacy call",
            explanation="Replaced call inside `run_cmd()`.",
            code_evidence="return old_unsafe(arg)",
        ),
        LLMCandidateItem(
            file_path="new_mod.py",
            diff_side=DiffSide.RIGHT,
            start_line=15,
            end_line=15,
            category=Category.BAO_TRI,
            finding_kind=FindingKind.GOI_Y_TOI_UU,
            severity=Severity.THAP,
            evidence_status=EvidenceStatus.CO_CAN_CU,
            title="Outside diff hunk",
            explanation="In bounds of file but outside hunks.",
            code_evidence="val_9 = 9",
        ),
    ]
    envelopes, invalid_orders = llm_items_to_envelopes(items, invocation_attempt=1)
    res = DeterministicGroundingGate().verify(
        envelopes=envelopes,
        snapshot=snapshot,
        parsed_files=parsed,
        base_contents={"old_mod.py": long_base},
        head_contents={"new_mod.py": long_head},
        invalid_order_indices=invalid_orders,
    )

    assert len(res.kept) == 2
    assert {e.candidate.title for e in res.kept} == {
        "Unescaped command argument",
        "Removed legacy call",
    }
    assert next(e for e in res.kept if e.candidate.title == "Removed legacy call").candidate.file_path == (
        "new_mod.py"
    )
    reasons = {r.filter_reason: r.filter_status for r in res.rejected}
    assert reasons["end_line_before_start_line"] == FilterStatus.LOAI_SAI_DONG
    assert reasons["line_outside_diff_hunks"] == FilterStatus.LOAI_SAI_DONG


def test_semantic_merger_clusters_ast_bandit_and_ruff_rule_families() -> None:
    sqli_candidates = [
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.AST_CUSTOM,
                diff_side=DiffSide.RIGHT,
                start_line=10,
                end_line=10,
                category=Category.BAO_MAT,
                severity=Severity.CAO,
                title="[AST04] Possible dynamic SQL query construction",
                raw_message="Dynamic SQL string inside execute().",
                code_evidence="cur.execute(f'SELECT * FROM t WHERE id={x}')",
                rule_code="AST04",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
            hunk_index=1,
        ),
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.BANDIT,
                diff_side=DiffSide.RIGHT,
                start_line=10,
                end_line=10,
                category=Category.BAO_MAT,
                severity=Severity.TRUNG_BINH,
                title="B608 hardcoded SQL",
                raw_message="Possible SQL injection vector.",
                code_evidence="cur.execute(f'SELECT * FROM t WHERE id={x}')",
                rule_code="B608",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
            hunk_index=1,
        ),
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.RUFF,
                diff_side=DiffSide.RIGHT,
                start_line=10,
                end_line=10,
                category=Category.BAO_MAT,
                severity=Severity.CAO,
                title="S608 hardcoded-sql-expression",
                raw_message="Possible SQL injection vector.",
                code_evidence="cur.execute(f'SELECT * FROM t WHERE id={x}')",
                rule_code="S608",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
            hunk_index=1,
        ),
    ]
    mut_candidates = [
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.AST_CUSTOM,
                diff_side=DiffSide.RIGHT,
                start_line=20,
                end_line=20,
                category=Category.CHUC_NANG,
                severity=Severity.CAO,
                title="[AST01] Mutable default argument",
                raw_message="Shared mutable default list.",
                code_evidence="def f(items=[]):",
                rule_code="AST01",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
            hunk_index=2,
        ),
        CandidateEnvelope(
            candidate=FindingCandidate(
                file_path="app.py",
                source_type=SourceType.RUFF,
                diff_side=DiffSide.RIGHT,
                start_line=20,
                end_line=20,
                category=Category.CHUC_NANG,
                severity=Severity.TRUNG_BINH,
                title="B006 mutable-argument-default",
                raw_message="Do not use mutable data structures for argument defaults.",
                code_evidence="def f(items=[]):",
                rule_code="B006",
            ),
            evidence_status=EvidenceStatus.CO_CAN_CU,
            hunk_index=2,
        ),
    ]

    merged = SemanticMerger().merge(sqli_candidates + mut_candidates)
    assert len(merged.findings) == 2
    sqli_f = next(f for f in merged.findings if f.category == Category.BAO_MAT)
    mut_f = next(f for f in merged.findings if f.category == Category.CHUC_NANG)
    assert set(sqli_f.sources) == {SourceType.AST_CUSTOM, SourceType.BANDIT, SourceType.RUFF}
    assert set(mut_f.sources) == {SourceType.AST_CUSTOM, SourceType.RUFF}
    kept_cnt = sum(1 for c in merged.updated_candidates if c.filter_status == FilterStatus.GIU_LAI)
    dup_cnt = sum(1 for c in merged.updated_candidates if c.filter_status == FilterStatus.LOAI_TRUNG)
    assert kept_cnt == 2
    assert dup_cnt == 3
