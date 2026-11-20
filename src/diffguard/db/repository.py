from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from diffguard.domain import (
    CodeSnapshot,
    FeedbackLabel,
    FindingFeedback,
    PublishStatus,
    ReviewReport,
    ReviewRequest,
)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ReviewStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def ensure_user(
        self,
        username: str,
        full_name: str,
        email: str | None = None,
        account_type: str = "CA_NHAN",
    ) -> int:
        row = self.conn.execute("SELECT user_id FROM UserAccount WHERE username = ?", (username,)).fetchone()
        if row is not None:
            return int(row["user_id"])
        cur = self.conn.execute(
            """INSERT INTO UserAccount (
                username, full_name, email, account_type, status, created_at
            ) VALUES (?, ?, ?, ?, 'HOAT_DONG', ?)""",
            (username, full_name, email, account_type, _iso(datetime.now(UTC))),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def ensure_repo(
        self,
        repo_full_name: str,
        platform: str = "CUC_BO",
        repo_url: str | None = None,
        default_branch: str = "main",
        primary_language: str = "Python",
    ) -> int:
        row = self.conn.execute(
            "SELECT repo_id FROM Repository WHERE repo_full_name = ?",
            (repo_full_name,),
        ).fetchone()
        if row is not None:
            return int(row["repo_id"])
        cur = self.conn.execute(
            """INSERT INTO Repository (
                repo_full_name, platform, repo_url, default_branch,
                primary_language, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'DANG_HOAT_DONG', ?)""",
            (
                repo_full_name,
                platform,
                repo_url,
                default_branch,
                primary_language,
                _iso(datetime.now(UTC)),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def grant_role(self, repo_id: int, user_id: int, role_name: str) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO RepositoryMember (
                repo_id, user_id, role_name, granted_at
            ) VALUES (?, ?, ?, ?)""",
            (repo_id, user_id, role_name, _iso(datetime.now(UTC))),
        )
        self.conn.commit()

    def upsert_pull_request(
        self,
        repo_id: int,
        pr_number: int,
        title: str,
        source_branch: str,
        target_branch: str,
        current_head_sha: str,
        pr_status: str = "DANG_MO",
        description: str | None = None,
        author_id: int | None = None,
    ) -> int:
        row = self.conn.execute(
            "SELECT pr_id FROM PullRequest WHERE repo_id = ? AND pr_number = ?",
            (repo_id, pr_number),
        ).fetchone()
        now = _iso(datetime.now(UTC))
        if row is not None:
            pr_id = int(row["pr_id"])
            self.conn.execute(
                """UPDATE PullRequest
                   SET title=?, description=?, source_branch=?, target_branch=?,
                       current_head_sha=?, pr_status=?, synced_at=?
                   WHERE pr_id=?""",
                (
                    title,
                    description,
                    source_branch,
                    target_branch,
                    current_head_sha,
                    pr_status,
                    now,
                    pr_id,
                ),
            )
            self.conn.commit()
            return pr_id
        cur = self.conn.execute(
            """INSERT INTO PullRequest (
                repo_id, author_id, pr_number, title, description, source_branch,
                target_branch, current_head_sha, pr_status, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                author_id,
                pr_number,
                title,
                description,
                source_branch,
                target_branch,
                current_head_sha,
                pr_status,
                now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_webhook_event(
        self,
        repo_id: int,
        pr_id: int | None,
        delivery_uuid: str,
        event_type: str,
        process_status: str,
        status_note: str | None = None,
    ) -> tuple[int, bool]:
        row = self.conn.execute(
            "SELECT event_id FROM WebhookEvent WHERE delivery_uuid = ?",
            (delivery_uuid,),
        ).fetchone()
        if row is not None:
            return int(row["event_id"]), False
        cur = self.conn.execute(
            """INSERT INTO WebhookEvent (
                repo_id, pr_id, delivery_uuid, event_type,
                process_status, status_note, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                pr_id,
                delivery_uuid,
                event_type,
                process_status,
                status_note,
                _iso(datetime.now(UTC)),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def ensure_prompt_template(
        self,
        prompt_code: str,
        version_tag: str,
        strategy_desc: str,
        system_prompt_text: str,
        user_prompt_template: str,
        output_json_schema: str,
        is_active: bool = True,
    ) -> int:
        row = self.conn.execute(
            "SELECT prompt_id FROM PromptTemplate WHERE prompt_code = ? AND version_tag = ?",
            (prompt_code, version_tag),
        ).fetchone()
        if row is not None:
            return int(row["prompt_id"])
        p_hash = _sha256_json([system_prompt_text, user_prompt_template, output_json_schema])
        cur = self.conn.execute(
            """INSERT INTO PromptTemplate (
                prompt_code, version_tag, strategy_desc, system_prompt_text,
                user_prompt_template, output_json_schema, prompt_hash,
                is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                prompt_code,
                version_tag,
                strategy_desc,
                system_prompt_text,
                user_prompt_template,
                output_json_schema,
                p_hash,
                int(is_active),
                _iso(datetime.now(UTC)),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def ensure_analysis_rule(
        self,
        tool_source: str,
        rule_code: str,
        rule_name: str,
        category: str,
        default_severity: str,
        rule_description: str | None = None,
        enabled_by_default: bool = True,
    ) -> int:
        row = self.conn.execute(
            "SELECT rule_id FROM AnalysisRule WHERE tool_source = ? AND rule_code = ?",
            (tool_source, rule_code),
        ).fetchone()
        if row is not None:
            return int(row["rule_id"])
        cur = self.conn.execute(
            """INSERT INTO AnalysisRule (
                tool_source, rule_code, rule_name, category,
                default_severity, rule_description, enabled_by_default
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                tool_source,
                rule_code,
                rule_name,
                category,
                default_severity,
                rule_description,
                int(enabled_by_default),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def ensure_review_config(
        self,
        repo_id: int,
        request: ReviewRequest,
        prompt_id: int | None,
        rule_overrides: list[tuple[int, bool, str | None]] | None = None,
    ) -> int:
        p = request.policy
        cfg_hash = _sha256_json([request.model_dump(mode="json"), prompt_id, rule_overrides or []])
        row = self.conn.execute(
            "SELECT config_id FROM ReviewConfig WHERE repo_id = ? AND config_hash = ?",
            (repo_id, cfg_hash),
        ).fetchone()
        if row is not None:
            return int(row["config_id"])
        max_ver_row = self.conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) AS mv FROM ReviewConfig WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()
        next_ver = int(max_ver_row["mv"]) + 1
        cur = self.conn.execute(
            """INSERT INTO ReviewConfig (
                repo_id, prompt_id, version_number, llm_model_name, temperature,
                max_files_limit, max_diff_lines, max_snapshot_bytes, max_input_tokens,
                max_output_tokens, max_llm_calls, timeout_seconds, allow_external_llm,
                auto_publish_pr, exclude_globs, config_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                prompt_id,
                next_ver,
                request.llm_model_name,
                p.temperature if request.llm_model_name else None,
                p.max_files_limit,
                p.max_diff_lines,
                p.max_snapshot_bytes,
                p.max_input_tokens,
                p.max_output_tokens,
                p.max_llm_calls,
                p.timeout_seconds,
                int(p.allow_external_llm),
                int(p.auto_publish_pr),
                ",".join(p.exclude_globs) if p.exclude_globs else None,
                cfg_hash,
                _iso(datetime.now(UTC)),
            ),
        )
        config_id = int(cur.lastrowid)
        for rule_id, is_enabled, sev_override in rule_overrides or []:
            self.conn.execute(
                """INSERT INTO ConfigRule (
                    config_id, rule_id, is_enabled, severity_override
                ) VALUES (?, ?, ?, ?)""",
                (config_id, rule_id, int(is_enabled), sev_override),
            )
        self.conn.commit()
        return config_id

    def save_snapshot(
        self,
        repo_id: int,
        snapshot: CodeSnapshot,
        pr_id: int | None = None,
    ) -> tuple[int, dict[str, int], dict[tuple[str, int], int]]:
        existing = self.conn.execute(
            """SELECT snapshot_id FROM CodeSnapshot
               WHERE repo_id=? AND base_commit_sha=? AND head_commit_sha=? AND diff_hash=?""",
            (repo_id, snapshot.base_commit_sha, snapshot.head_commit_sha, snapshot.diff_hash),
        ).fetchone()
        if existing is not None:
            sid = int(existing["snapshot_id"])
            return sid, *self._load_snapshot_maps(sid)
        cur = self.conn.execute(
            """INSERT INTO CodeSnapshot (
                repo_id, pr_id, input_source, base_commit_sha, head_commit_sha,
                merge_base_sha, diff_hash, total_files, total_additions, total_deletions, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                pr_id,
                snapshot.input_source.value,
                snapshot.base_commit_sha,
                snapshot.head_commit_sha,
                snapshot.merge_base_sha,
                snapshot.diff_hash,
                snapshot.total_files,
                snapshot.total_additions,
                snapshot.total_deletions,
                _iso(datetime.now(UTC)),
            ),
        )
        sid = int(cur.lastrowid)
        file_map: dict[str, int] = {}
        hunk_map: dict[tuple[str, int], int] = {}
        for cf in snapshot.files:
            fcur = self.conn.execute(
                """INSERT INTO ChangedFile (
                    snapshot_id, old_path, new_path, change_type, patch_status, language,
                    old_line_count, new_line_count, additions_count, deletions_count, is_supported
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    cf.old_path,
                    cf.new_path,
                    cf.change_type.value,
                    cf.patch_status.value,
                    cf.language,
                    cf.old_line_count,
                    cf.new_line_count,
                    cf.additions_count,
                    cf.deletions_count,
                    int(cf.is_supported),
                ),
            )
            fid = int(fcur.lastrowid)
            file_map[cf.display_path] = fid
            for hk in cf.hunks:
                hcur = self.conn.execute(
                    """INSERT INTO DiffHunk (
                        file_id, hunk_index, old_start_line, old_line_span, new_start_line,
                        new_line_span, ast_symbol_name, patch_content, ast_context_snippet, estimated_tokens
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fid,
                        hk.hunk_index,
                        hk.old_start_line,
                        hk.old_line_span,
                        hk.new_start_line,
                        hk.new_line_span,
                        hk.ast_symbol_name,
                        hk.patch_content,
                        hk.ast_context_snippet,
                        hk.estimated_tokens,
                    ),
                )
                hunk_map[(cf.display_path, hk.hunk_index)] = int(hcur.lastrowid)
        self.conn.commit()
        return sid, file_map, hunk_map

    def _load_snapshot_maps(self, snapshot_id: int) -> tuple[dict[str, int], dict[tuple[str, int], int]]:
        file_map: dict[str, int] = {}
        hunk_map: dict[tuple[str, int], int] = {}
        rows = self.conn.execute(
            "SELECT file_id, old_path, new_path FROM ChangedFile WHERE snapshot_id=?",
            (snapshot_id,),
        )
        for f in rows:
            path = f["new_path"] or f["old_path"]
            fid = int(f["file_id"])
            file_map[path] = fid
            hunks = self.conn.execute("SELECT hunk_id, hunk_index FROM DiffHunk WHERE file_id=?", (fid,))
            for h in hunks:
                hunk_map[(path, int(h["hunk_index"]))] = int(h["hunk_id"])
        return file_map, hunk_map

    def create_run(
        self,
        snapshot_id: int,
        config_id: int,
        request: ReviewRequest,
        idempotency_key: str,
        requested_by: int | None = None,
        event_id: int | None = None,
        retention_days: int = 30,
    ) -> tuple[int, bool]:
        existing = self.conn.execute(
            "SELECT run_id FROM ReviewRun WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            return int(existing["run_id"]), False
        now = datetime.now(UTC)
        cur = self.conn.execute(
            """INSERT INTO ReviewRun (
                snapshot_id, config_id, requested_by, event_id, idempotency_key,
                execution_mode, context_policy, run_status, is_full_coverage,
                termination_reason, benchmark_sample_id, benchmark_manifest_hash,
                created_at, retention_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CHO_XU_LY', 1, NULL, ?, ?, ?, ?)""",
            (
                snapshot_id,
                config_id,
                requested_by,
                event_id,
                idempotency_key,
                request.execution_mode.value,
                request.context_policy.value,
                request.benchmark_sample_id,
                request.benchmark_manifest_hash,
                _iso(now),
                _iso(now + timedelta(days=retention_days)),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def persist_report(
        self,
        run_id: int,
        snapshot_id: int,
        file_map: dict[str, int],
        hunk_map: dict[tuple[str, int], int],
        report: ReviewReport,
    ) -> None:
        self.conn.execute(
            """UPDATE ReviewRun
               SET run_status=?, is_full_coverage=?, termination_reason=?,
                   started_at=?, finished_at=?
               WHERE run_id=?""",
            (
                report.run_status.value,
                int(report.is_full_coverage),
                report.termination_reason,
                _iso(report.started_at),
                _iso(report.finished_at),
                run_id,
            ),
        )
        inv_map: dict[int, int] = {}
        for inv in report.invocations:
            hk_id = None
            if inv.hunk_index is not None:
                for (_fp, hi), hid in hunk_map.items():
                    if hi == inv.hunk_index:
                        hk_id = hid
                        break
            cur = self.conn.execute(
                """INSERT INTO ModelInvocation (
                    run_id, hunk_id, attempt_number, call_purpose, provider_name,
                    resolved_model_name, payload_hash, call_status, input_tokens,
                    output_tokens, usage_source, estimated_cost_usd, latency_ms,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    hk_id,
                    inv.attempt_number,
                    inv.call_purpose.value,
                    inv.provider_name,
                    inv.resolved_model_name,
                    inv.payload_hash,
                    inv.call_status.value,
                    inv.input_tokens,
                    inv.output_tokens,
                    inv.usage_source.value,
                    inv.estimated_cost_usd,
                    inv.latency_ms,
                    _iso(inv.started_at),
                    _iso(inv.finished_at),
                ),
            )
            inv_map[inv.attempt_number] = int(cur.lastrowid)

        for qa in report.quality_assessments:
            self.conn.execute(
                """INSERT INTO QualityAssessment (
                    run_id, dimension_name, rubric_version, assessment_status,
                    is_scope_complete, summary_rationale
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    qa.dimension_name.value,
                    qa.rubric_version,
                    qa.assessment_status.value,
                    int(qa.is_scope_complete),
                    qa.summary_rationale,
                ),
            )

        finding_map: dict[str, int] = {}
        for fnd in report.findings:
            fid = file_map[fnd.file_path]
            hk_id = hunk_map.get((fnd.file_path, fnd.hunk_index)) if fnd.hunk_index else None
            cur = self.conn.execute(
                """INSERT INTO ReviewFinding (
                    run_id, snapshot_id, file_id, hunk_id, issue_fingerprint,
                    diff_side, start_line, end_line, category, finding_kind,
                    severity, evidence_status, title, explanation, code_evidence,
                    suggested_fix, fix_verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    snapshot_id,
                    fid,
                    hk_id,
                    fnd.issue_fingerprint,
                    fnd.diff_side.value,
                    fnd.start_line,
                    fnd.end_line,
                    fnd.category.value,
                    fnd.finding_kind.value,
                    fnd.severity.value,
                    fnd.evidence_status.value,
                    fnd.title,
                    fnd.explanation,
                    fnd.code_evidence,
                    fnd.suggested_fix,
                    fnd.fix_verification_status.value,
                ),
            )
            finding_map[fnd.issue_fingerprint] = int(cur.lastrowid)

        for cand in report.candidates:
            fid = file_map[cand.file_path]
            rule_id = None
            if cand.rule_code:
                rule_id = self.ensure_analysis_rule(
                    cand.source_type.value,
                    cand.rule_code,
                    cand.title[:200],
                    cand.category.value,
                    cand.severity.value,
                )
            inv_id = inv_map.get(cand.invocation_attempt) if cand.invocation_attempt else None
            fnd_id = finding_map.get(cand.merged_fingerprint) if cand.merged_fingerprint else None
            self.conn.execute(
                """INSERT INTO FindingCandidate (
                    run_id, file_id, rule_id, invocation_id, finding_id, source_type,
                    diff_side, start_line, end_line, raw_message, filter_status, filter_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    fid,
                    rule_id,
                    inv_id,
                    fnd_id,
                    cand.source_type.value,
                    cand.diff_side.value,
                    cand.start_line,
                    cand.end_line,
                    cand.raw_message,
                    cand.filter_status.value,
                    cand.filter_reason,
                ),
            )
        self.conn.commit()

    def add_feedback(
        self,
        finding_id: int,
        user_id: int,
        feedback_label: FeedbackLabel,
        reason_note: str | None = None,
    ) -> FindingFeedback:
        if feedback_label == FeedbackLabel.SAI and (not reason_note or not reason_note.strip()):
            raise ValueError("reason_note is required when feedback_label is SAI")
        row = self.conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) AS mr "
            "FROM FindingFeedback WHERE finding_id=? AND user_id=?",
            (finding_id, user_id),
        ).fetchone()
        rev = int(row["mr"]) + 1
        now = datetime.now(UTC)
        self.conn.execute(
            """INSERT INTO FindingFeedback (
                finding_id, user_id, revision_no, feedback_label, reason_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (finding_id, user_id, rev, feedback_label.value, reason_note, _iso(now)),
        )
        self.conn.commit()
        return FindingFeedback(
            finding_id=finding_id,
            user_id=user_id,
            revision_no=rev,
            feedback_label=feedback_label,
            reason_note=reason_note,
            created_at=now,
        )

    def upsert_publication(
        self,
        run_id: int,
        finding_id: int | None,
        comment_scope: str,
        marker_key: str,
        target_commit_sha: str,
        publish_status: PublishStatus,
        external_comment_id: str | None = None,
        retry_count: int = 0,
        status_detail: str | None = None,
    ) -> int:
        now = _iso(datetime.now(UTC))
        if finding_id is None:
            row = self.conn.execute(
                "SELECT publication_id FROM PublicationRecord WHERE run_id=? AND finding_id IS NULL",
                (run_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT publication_id FROM PublicationRecord WHERE run_id=? AND finding_id=?",
                (run_id, finding_id),
            ).fetchone()
        if row is not None:
            pid = int(row["publication_id"])
            self.conn.execute(
                """UPDATE PublicationRecord SET target_commit_sha=?, publish_status=?,
                   external_comment_id=COALESCE(?, external_comment_id), retry_count=?,
                   status_detail=?, updated_at=? WHERE publication_id=?""",
                (
                    target_commit_sha,
                    publish_status.value,
                    external_comment_id,
                    retry_count,
                    status_detail,
                    now,
                    pid,
                ),
            )
            self.conn.commit()
            return pid
        cur = self.conn.execute(
            """INSERT INTO PublicationRecord (
                run_id, finding_id, comment_scope, marker_key, target_commit_sha,
                publish_status, external_comment_id, retry_count, status_detail, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                finding_id,
                comment_scope,
                marker_key,
                target_commit_sha,
                publish_status.value,
                external_comment_id,
                retry_count,
                status_detail,
                now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def register_artifact(
        self,
        artifact_type: str,
        storage_uri: str,
        content_sha256: str,
        size_bytes: int,
        expires_at: datetime,
        snapshot_id: int | None = None,
        run_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO StorageArtifact (
                snapshot_id, run_id, artifact_type, storage_uri, content_sha256,
                size_bytes, purge_status, expires_at, purged_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'CON_LUU', ?, NULL, ?)""",
            (
                snapshot_id,
                run_id,
                artifact_type,
                storage_uri,
                content_sha256,
                size_bytes,
                _iso(expires_at),
                _iso(datetime.now(UTC)),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def purge_expired_artifacts(
        self,
        now: datetime,
        delete_storage_fn: Callable[[str], bool],
    ) -> dict[str, int]:
        now_s = _iso(now)
        assert now_s is not None
        rows = self.conn.execute(
            """SELECT artifact_id, snapshot_id, artifact_type, storage_uri
               FROM StorageArtifact
               WHERE purge_status IN ('CON_LUU', 'LOI_XOA') AND expires_at <= ?""",
            (now_s,),
        ).fetchall()
        purged = 0
        failed = 0
        purged_snapshots: set[int] = set()
        for row in rows:
            uri = str(row["storage_uri"])
            aid = int(row["artifact_id"])
            try:
                deleted = delete_storage_fn(uri)
            except OSError:
                deleted = False
            if deleted:
                self.conn.execute(
                    "UPDATE StorageArtifact SET purge_status='DA_XOA', purged_at=? WHERE artifact_id=?",
                    (now_s, aid),
                )
                purged += 1
                if row["snapshot_id"] is not None and str(row["artifact_type"]).startswith("RAW_"):
                    purged_snapshots.add(int(row["snapshot_id"]))
            else:
                self.conn.execute(
                    "UPDATE StorageArtifact SET purge_status='LOI_XOA' WHERE artifact_id=?",
                    (aid,),
                )
                failed += 1
        for sid in purged_snapshots:
            self.conn.execute(
                """UPDATE DiffHunk SET patch_content=NULL, ast_context_snippet=NULL
                   WHERE file_id IN (SELECT file_id FROM ChangedFile WHERE snapshot_id=?)""",
                (sid,),
            )
        self.conn.execute(
            """DELETE FROM StorageArtifact
               WHERE purge_status='DA_XOA'
                 AND run_id IN (SELECT run_id FROM ReviewRun WHERE retention_expires_at <= ?)""",
            (now_s,),
        )
        expired_runs = self.conn.execute(
            """DELETE FROM ReviewRun
               WHERE retention_expires_at <= ?
                 AND NOT EXISTS (
                     SELECT 1 FROM StorageArtifact sa
                     WHERE sa.run_id = ReviewRun.run_id AND sa.purge_status <> 'DA_XOA'
                 )""",
            (now_s,),
        ).rowcount
        self.conn.commit()
        return {"artifacts_purged": purged, "artifacts_failed": failed, "runs_deleted": int(expired_runs)}

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT r.run_id, r.execution_mode, r.context_policy, r.run_status, r.is_full_coverage,
                      r.created_at, r.finished_at, r.termination_reason,
                      s.head_commit_sha, s.base_commit_sha, s.total_files,
                      s.total_additions, s.total_deletions,
                      repo.repo_full_name, pr.pr_number, pr.current_head_sha,
                      (SELECT COUNT(*) FROM ReviewFinding rf WHERE rf.run_id = r.run_id) AS finding_count
               FROM ReviewRun r
               JOIN CodeSnapshot s ON s.snapshot_id = r.snapshot_id
               JOIN Repository repo ON repo.repo_id = s.repo_id
               LEFT JOIN PullRequest pr ON pr.pr_id = s.pr_id
               ORDER BY r.run_id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["is_stale"] = bool(
                item["current_head_sha"] is not None and item["current_head_sha"] != item["head_commit_sha"]
            )
            results.append(item)
        return results

    def get_run_detail(self, run_id: int) -> dict[str, Any] | None:
        r = self.conn.execute(
            """SELECT r.*, s.repo_id, s.pr_id, s.input_source, s.base_commit_sha, s.head_commit_sha,
                      s.merge_base_sha, s.diff_hash, s.total_files, s.total_additions, s.total_deletions,
                      repo.repo_full_name, pr.pr_number, pr.title AS pr_title, pr.current_head_sha
               FROM ReviewRun r
               JOIN CodeSnapshot s ON s.snapshot_id = r.snapshot_id
               JOIN Repository repo ON repo.repo_id = s.repo_id
               LEFT JOIN PullRequest pr ON pr.pr_id = s.pr_id
               WHERE r.run_id = ?""",
            (run_id,),
        ).fetchone()
        if r is None:
            return None
        data = dict(r)
        data["is_stale"] = bool(
            data["current_head_sha"] is not None and data["current_head_sha"] != data["head_commit_sha"]
        )
        findings = [
            dict(x)
            for x in self.conn.execute(
                """SELECT rf.*, COALESCE(cf.new_path, cf.old_path) AS file_path
                   FROM ReviewFinding rf
                   JOIN ChangedFile cf ON cf.file_id = rf.file_id
                   WHERE rf.run_id = ? ORDER BY rf.finding_id ASC""",
                (run_id,),
            ).fetchall()
        ]
        for f in findings:
            fbs = [
                dict(fb)
                for fb in self.conn.execute(
                    """SELECT ff.*, u.username FROM FindingFeedback ff
                       JOIN UserAccount u ON u.user_id = ff.user_id
                       WHERE ff.finding_id=? ORDER BY ff.revision_no DESC""",
                    (f["finding_id"],),
                ).fetchall()
            ]
            f["feedbacks"] = fbs
            cands = [
                dict(c)
                for c in self.conn.execute(
                    "SELECT source_type, raw_message FROM FindingCandidate WHERE finding_id=?",
                    (f["finding_id"],),
                ).fetchall()
            ]
            f["sources"] = sorted({c["source_type"] for c in cands})
        data["findings"] = findings
        data["candidates"] = [
            dict(c)
            for c in self.conn.execute(
                """SELECT fc.*, COALESCE(cf.new_path, cf.old_path) AS file_path
                   FROM FindingCandidate fc JOIN ChangedFile cf ON cf.file_id = fc.file_id
                   WHERE fc.run_id = ? ORDER BY fc.candidate_id ASC""",
                (run_id,),
            ).fetchall()
        ]
        data["quality_assessments"] = [
            dict(q)
            for q in self.conn.execute(
                "SELECT * FROM QualityAssessment WHERE run_id=? ORDER BY assessment_id ASC",
                (run_id,),
            ).fetchall()
        ]
        data["invocations"] = [
            dict(m)
            for m in self.conn.execute(
                "SELECT * FROM ModelInvocation WHERE run_id=? ORDER BY attempt_number ASC",
                (run_id,),
            ).fetchall()
        ]
        data["publications"] = [
            dict(p)
            for p in self.conn.execute(
                "SELECT * FROM PublicationRecord WHERE run_id=? ORDER BY publication_id ASC",
                (run_id,),
            ).fetchall()
        ]
        return data
