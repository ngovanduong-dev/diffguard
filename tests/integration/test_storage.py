import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from diffguard.db import ReviewStore, init_schema, open_connection
from diffguard.domain import (
    AssessmentStatus,
    CallPurpose,
    CallStatus,
    Category,
    ChangedFile,
    ChangeType,
    CodeSnapshot,
    ContextPolicy,
    DiffHunk,
    DiffSide,
    EvidenceStatus,
    ExecutionMode,
    FeedbackLabel,
    FilterStatus,
    FindingCandidate,
    FindingKind,
    FixVerificationStatus,
    InputSource,
    ModelInvocationRecord,
    PatchStatus,
    PublishStatus,
    QualityAssessment,
    ReviewFinding,
    ReviewPolicy,
    ReviewReport,
    ReviewRequest,
    RunStatus,
    Severity,
    SourceType,
    UsageSource,
)


def _seed_report(now: datetime) -> tuple[ReviewRequest, CodeSnapshot, ReviewReport]:
    req = ReviewRequest(
        repo_full_name="org/demo",
        execution_mode=ExecutionMode.D_KET_HOP,
        context_policy=ContextPolicy.DIFF_AST_INTENT,
        llm_model_name="gemini-2.5-flash",
        prompt_code="PY_HYBRID_AST",
        prompt_version="v1.0",
        benchmark_sample_id="S-001",
        benchmark_manifest_hash="m" * 64,
        policy=ReviewPolicy(allow_external_llm=True),
    )
    snap = CodeSnapshot(
        repo_full_name="org/demo",
        input_source=InputSource.GITHUB_PR,
        base_commit_sha="a" * 40,
        head_commit_sha="b" * 40,
        merge_base_sha="c" * 40,
        diff_hash="d" * 64,
        total_files=2,
        total_additions=6,
        total_deletions=2,
        pr_number=42,
        pr_title="Fix sql query",
        files=[
            ChangedFile(
                old_path="app/db.py",
                new_path="app/db.py",
                change_type=ChangeType.CHINH_SUA,
                patch_status=PatchStatus.CO_PATCH,
                old_line_count=20,
                new_line_count=24,
                additions_count=6,
                deletions_count=2,
                hunks=[
                    DiffHunk(
                        hunk_index=1,
                        old_start_line=10,
                        old_line_span=3,
                        new_start_line=10,
                        new_line_span=7,
                        ast_symbol_name="get_user",
                        patch_content="@@ -10,3 +10,7 @@",
                        ast_context_snippet="def get_user(uid):\n    pass",
                        estimated_tokens=30,
                    )
                ],
            ),
            ChangedFile(
                old_path=None,
                new_path="assets/logo.png",
                change_type=ChangeType.THEM_MOI,
                patch_status=PatchStatus.NHI_PHAN,
                language="Binary",
                is_supported=False,
            ),
        ],
    )
    qas = [
        QualityAssessment(
            dimension_name=cat,
            rubric_version="rubric-v1",
            assessment_status=(
                AssessmentStatus.CO_VAN_DE
                if cat == Category.BAO_MAT
                else AssessmentStatus.KHONG_QUAN_SAT_THAY
            ),
            is_scope_complete=True,
            summary_rationale="Checked",
        )
        for cat in Category
    ]
    inv = ModelInvocationRecord(
        attempt_number=1,
        call_purpose=CallPurpose.REVIEW,
        provider_name="gemini",
        resolved_model_name="gemini-2.5-flash",
        payload_hash="p" * 64,
        call_status=CallStatus.THANH_CONG,
        input_tokens=200,
        output_tokens=60,
        usage_source=UsageSource.THUC_TE,
        estimated_cost_usd=0.0,
        latency_ms=420,
        started_at=now,
        finished_at=now + timedelta(milliseconds=420),
        hunk_index=1,
    )
    inv_fail = ModelInvocationRecord(
        attempt_number=2,
        call_purpose=CallPurpose.XAC_MINH,
        provider_name="groq",
        resolved_model_name="qwen3",
        payload_hash="q" * 64,
        call_status=CallStatus.QUA_HAN,
        usage_source=UsageSource.KHONG_CO,
        latency_ms=3000,
        started_at=now,
        finished_at=now + timedelta(seconds=3),
    )
    finding = ReviewFinding(
        issue_fingerprint="fp-sqli-1",
        file_path="app/db.py",
        diff_side=DiffSide.RIGHT,
        start_line=12,
        end_line=13,
        hunk_index=1,
        category=Category.BAO_MAT,
        finding_kind=FindingKind.LOI_TIEM_AN,
        severity=Severity.CAO,
        evidence_status=EvidenceStatus.CO_CAN_CU,
        title="SQL injection via f-string",
        explanation="User input interpolated into SQL query",
        code_evidence="cur.execute(f'SELECT * FROM u WHERE id={uid}')",
        suggested_fix="cur.execute('SELECT * FROM u WHERE id=?', (uid,))",
        fix_verification_status=FixVerificationStatus.CHUA_KIEM_CHUNG,
        sources=[SourceType.BANDIT, SourceType.LLM],
    )
    cands = [
        FindingCandidate(
            file_path="app/db.py",
            source_type=SourceType.BANDIT,
            diff_side=DiffSide.RIGHT,
            start_line=12,
            end_line=13,
            category=Category.BAO_MAT,
            severity=Severity.CAO,
            title="hardcoded_sql_expressions",
            raw_message="B608",
            rule_code="B608",
            filter_status=FilterStatus.GIU_LAI,
            merged_fingerprint="fp-sqli-1",
        ),
        FindingCandidate(
            file_path="app/db.py",
            source_type=SourceType.LLM,
            diff_side=DiffSide.RIGHT,
            start_line=12,
            end_line=13,
            category=Category.BAO_MAT,
            severity=Severity.CAO,
            title="SQL injection",
            raw_message="SQLi",
            invocation_attempt=1,
            filter_status=FilterStatus.GIU_LAI,
            merged_fingerprint="fp-sqli-1",
        ),
        FindingCandidate(
            file_path="app/db.py",
            source_type=SourceType.AST_CUSTOM,
            diff_side=DiffSide.RIGHT,
            start_line=5,
            end_line=5,
            category=Category.CHUC_NANG,
            severity=Severity.TRUNG_BINH,
            title="mutable default",
            raw_message="AST01",
            rule_code="AST01",
            filter_status=FilterStatus.LOI_CU,
            filter_reason="Present at merge_base",
        ),
    ]
    rep = ReviewReport(
        idempotency_key="idem-42",
        snapshot=snap,
        execution_mode=ExecutionMode.D_KET_HOP,
        context_policy=ContextPolicy.DIFF_AST_INTENT,
        run_status=RunStatus.HOAN_THANH,
        is_full_coverage=True,
        findings=[finding],
        candidates=cands,
        quality_assessments=qas,
        invocations=[inv, inv_fail],
        created_at=now,
        started_at=now,
        finished_at=now + timedelta(seconds=4),
    )
    return req, snap, rep


def test_full_20_table_persistence_constraints_and_retention(tmp_path: Path) -> None:
    db_file = tmp_path / "diffguard.db"
    conn = open_connection(db_file)
    init_schema(conn)

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    assert len(tables) == 20
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    store = ReviewStore(conn)
    uid = store.ensure_user("dev1", "Developer One", "dev1@example.com")
    rid = store.ensure_repo("org/demo", platform="GITHUB", repo_url="https://github.com/org/demo")
    store.grant_role(rid, uid, "QUAN_LY_DU_AN")
    store.grant_role(rid, uid, "NGUOI_REVIEW")
    pid = store.upsert_pull_request(rid, 42, "Fix sql query", "feat/sql", "main", "b" * 40, author_id=uid)
    ev_id, created_ev = store.record_webhook_event(rid, pid, "deliv-100", "pull_request", "DA_TAO_LUOT")
    assert created_ev is True
    ev_id2, created_ev2 = store.record_webhook_event(rid, pid, "deliv-100", "pull_request", "DA_TAO_LUOT")
    assert ev_id2 == ev_id and created_ev2 is False

    pr_tpl = store.ensure_prompt_template(
        "PY_HYBRID_AST", "v1.0", "desc", "sys", "{{diff}}", '{"type":"object"}'
    )
    r_id = store.ensure_analysis_rule("BANDIT", "B608", "hardcoded_sql_expressions", "BAO_MAT", "CAO")
    cfg_req = ReviewRequest(
        repo_full_name="org/demo",
        execution_mode=ExecutionMode.D_KET_HOP,
        llm_model_name="gemini-2.5-flash",
    )
    cfg_id = store.ensure_review_config(rid, cfg_req, pr_tpl, [(r_id, True, "CAO")])

    cfg_a_req = ReviewRequest(repo_full_name="org/demo", execution_mode=ExecutionMode.A_STATIC)
    cfg_a_id = store.ensure_review_config(rid, cfg_a_req, None)
    assert cfg_a_id != cfg_id

    now = datetime.now(UTC)
    req, snap, rep = _seed_report(now)
    sid, f_map, h_map = store.save_snapshot(rid, snap, pr_id=pid)
    run_id, created_run = store.create_run(
        sid, cfg_id, req, "idem-42", requested_by=uid, event_id=ev_id, retention_days=30
    )
    assert created_run is True
    run_id_dup, created_dup = store.create_run(sid, cfg_id, req, "idem-42", requested_by=uid, event_id=ev_id)
    assert run_id_dup == run_id and created_dup is False

    store.persist_report(run_id, sid, f_map, h_map, rep)
    detail = store.get_run_detail(run_id)
    assert detail is not None
    assert len(detail["findings"]) == 1
    assert set(detail["findings"][0]["sources"]) == {"BANDIT", "LLM"}
    assert len(detail["candidates"]) == 3
    assert len(detail["quality_assessments"]) == 5
    assert len(detail["invocations"]) == 2
    assert detail["is_stale"] is False

    store.upsert_pull_request(rid, 42, "Fix sql query", "feat/sql", "main", "f" * 40, author_id=uid)
    detail_stale = store.get_run_detail(run_id)
    assert detail_stale is not None and detail_stale["is_stale"] is True

    fid_db = int(detail["findings"][0]["finding_id"])
    with pytest.raises(ValueError):
        store.add_feedback(fid_db, uid, FeedbackLabel.SAI, "  ")
    fb1 = store.add_feedback(fid_db, uid, FeedbackLabel.DUNG)
    fb2 = store.add_feedback(fid_db, uid, FeedbackLabel.SAI, "Guarded by allowlist")
    assert fb1.revision_no == 1 and fb2.revision_no == 2

    pub_sum = store.upsert_publication(
        run_id,
        None,
        "TONG_HOP_PR",
        "dg:sum:42",
        "b" * 40,
        PublishStatus.CAN_DOI_SOAT,
        retry_count=1,
        status_detail="timeout",
    )
    pub_sum_upd = store.upsert_publication(
        run_id,
        None,
        "TONG_HOP_PR",
        "dg:sum:42",
        "b" * 40,
        PublishStatus.DA_DANG,
        external_comment_id="gh-101",
    )
    assert pub_sum == pub_sum_upd
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO PublicationRecord (
                run_id, finding_id, comment_scope, marker_key,
                target_commit_sha, publish_status, retry_count, updated_at
            ) VALUES (?, NULL, 'TONG_HOP_PR', 'dup', 'b', 'CHO_DANG', 0, ?)""",
            (run_id, now.isoformat()),
        )

    raw_file = tmp_path / "raw_snap.json"
    raw_file.write_text("{}", encoding="utf-8")
    store.register_artifact(
        "RAW_SNAPSHOT",
        str(raw_file),
        "h" * 64,
        2,
        now + timedelta(days=7),
        snapshot_id=sid,
        run_id=run_id,
    )
    store.register_artifact(
        "REPORT_JSON",
        str(tmp_path / "rep.json"),
        "j" * 64,
        10,
        now + timedelta(days=30),
        run_id=run_id,
    )

    res_8d = store.purge_expired_artifacts(
        now + timedelta(days=8),
        lambda uri: Path(uri).unlink(missing_ok=True) or True,
    )
    assert res_8d["artifacts_purged"] == 1
    assert res_8d["runs_deleted"] == 0
    assert not raw_file.exists()
    hunk_row = conn.execute(
        "SELECT patch_content, ast_context_snippet, ast_symbol_name FROM DiffHunk"
    ).fetchone()
    assert hunk_row["patch_content"] is None and hunk_row["ast_context_snippet"] is None
    assert hunk_row["ast_symbol_name"] == "get_user"
    assert store.get_run_detail(run_id) is not None

    store.register_artifact(
        "REPORT_MD",
        str(tmp_path / "missing.md"),
        "k" * 64,
        10,
        now + timedelta(days=9),
        run_id=run_id,
    )
    res_fail = store.purge_expired_artifacts(now + timedelta(days=10), lambda _uri: False)
    assert res_fail["artifacts_failed"] == 1

    res_31d = store.purge_expired_artifacts(now + timedelta(days=31), lambda _uri: True)
    assert res_31d["runs_deleted"] == 1
    assert store.get_run_detail(run_id) is None
    conn.close()
