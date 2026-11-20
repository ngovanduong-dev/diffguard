PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS UserAccount (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      VARCHAR(100) NOT NULL UNIQUE,
    full_name     VARCHAR(150) NOT NULL,
    email         VARCHAR(150) NULL UNIQUE,
    account_type  VARCHAR(30)  NOT NULL CHECK (account_type IN ('CA_NHAN', 'DICH_VU_CI')),
    status        VARCHAR(30)  NOT NULL CHECK (status IN ('HOAT_DONG', 'TAM_KHOA')),
    created_at    DATETIME     NOT NULL
);

CREATE TABLE IF NOT EXISTS Repository (
    repo_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_full_name   VARCHAR(200) NOT NULL UNIQUE,
    platform         VARCHAR(30)  NOT NULL CHECK (platform IN ('GITHUB', 'CUC_BO')),
    repo_url         VARCHAR(500) NULL,
    default_branch   VARCHAR(100) NOT NULL,
    primary_language VARCHAR(50)  NOT NULL,
    status           VARCHAR(30)  NOT NULL CHECK (status IN ('DANG_HOAT_DONG', 'NGUNG_THEO_DOI')),
    created_at       DATETIME     NOT NULL
);

CREATE TABLE IF NOT EXISTS RepositoryMember (
    member_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id    INTEGER     NOT NULL REFERENCES Repository(repo_id) ON DELETE CASCADE,
    user_id    INTEGER     NOT NULL REFERENCES UserAccount(user_id) ON DELETE CASCADE,
    role_name  VARCHAR(30) NOT NULL CHECK (role_name IN ('LAP_TRINH_VIEN', 'NGUOI_REVIEW', 'QUAN_LY_DU_AN', 'NGUOI_DANH_GIA')),
    granted_at DATETIME    NOT NULL,
    UNIQUE (repo_id, user_id, role_name)
);

CREATE TABLE IF NOT EXISTS PullRequest (
    pr_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id          INTEGER      NOT NULL REFERENCES Repository(repo_id) ON DELETE RESTRICT,
    author_id        INTEGER      NULL REFERENCES UserAccount(user_id) ON DELETE SET NULL,
    pr_number        INTEGER      NOT NULL CHECK (pr_number > 0),
    title            VARCHAR(300) NOT NULL,
    description      TEXT         NULL,
    source_branch    VARCHAR(120) NOT NULL,
    target_branch    VARCHAR(120) NOT NULL,
    current_head_sha VARCHAR(64)  NOT NULL,
    pr_status        VARCHAR(30)  NOT NULL CHECK (pr_status IN ('DANG_MO', 'DA_DONG', 'DA_HOP_NHAT')),
    synced_at        DATETIME     NOT NULL,
    UNIQUE (repo_id, pr_number),
    UNIQUE (repo_id, pr_id)
);

CREATE TABLE IF NOT EXISTS WebhookEvent (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id        INTEGER      NOT NULL REFERENCES Repository(repo_id) ON DELETE RESTRICT,
    pr_id          INTEGER      NULL,
    delivery_uuid  VARCHAR(128) NOT NULL UNIQUE,
    event_type     VARCHAR(80)  NOT NULL,
    process_status VARCHAR(30)  NOT NULL CHECK (process_status IN ('TIEP_NHAN', 'DA_TAO_LUOT', 'BO_QUA', 'LOI')),
    status_note    VARCHAR(500) NULL,
    received_at    DATETIME     NOT NULL,
    FOREIGN KEY (repo_id, pr_id) REFERENCES PullRequest(repo_id, pr_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS CodeSnapshot (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id         INTEGER     NOT NULL REFERENCES Repository(repo_id) ON DELETE RESTRICT,
    pr_id           INTEGER     NULL,
    input_source    VARCHAR(30) NOT NULL CHECK (input_source IN ('GITHUB_PR', 'CLI_CUC_BO', 'IDE_PLUGIN')),
    base_commit_sha VARCHAR(64) NOT NULL,
    head_commit_sha VARCHAR(64) NOT NULL,
    merge_base_sha  VARCHAR(64) NOT NULL,
    diff_hash       VARCHAR(64) NOT NULL,
    total_files     INTEGER     NOT NULL CHECK (total_files >= 0),
    total_additions INTEGER     NOT NULL CHECK (total_additions >= 0),
    total_deletions INTEGER     NOT NULL CHECK (total_deletions >= 0),
    created_at      DATETIME    NOT NULL,
    UNIQUE (repo_id, base_commit_sha, head_commit_sha, diff_hash),
    FOREIGN KEY (repo_id, pr_id) REFERENCES PullRequest(repo_id, pr_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ChangedFile (
    file_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER      NOT NULL REFERENCES CodeSnapshot(snapshot_id) ON DELETE CASCADE,
    old_path        VARCHAR(500) NULL,
    new_path        VARCHAR(500) NULL,
    change_type     VARCHAR(20)  NOT NULL CHECK (change_type IN ('THEM_MOI', 'CHINH_SUA', 'XOA', 'DOI_TEN')),
    patch_status    VARCHAR(30)  NOT NULL DEFAULT 'CO_PATCH' CHECK (patch_status IN ('CO_PATCH', 'THIEU_PATCH', 'NHI_PHAN', 'NGOAI_PHAM_VI')),
    language        VARCHAR(50)  NOT NULL,
    old_line_count  INTEGER      NOT NULL CHECK (old_line_count >= 0),
    new_line_count  INTEGER      NOT NULL CHECK (new_line_count >= 0),
    additions_count INTEGER      NOT NULL CHECK (additions_count >= 0),
    deletions_count INTEGER      NOT NULL CHECK (deletions_count >= 0),
    is_supported    BOOLEAN      NOT NULL CHECK (is_supported IN (0, 1)),
    UNIQUE (snapshot_id, file_id),
    CHECK (
        (change_type = 'THEM_MOI' AND old_path IS NULL AND new_path IS NOT NULL) OR
        (change_type = 'XOA' AND old_path IS NOT NULL AND new_path IS NULL) OR
        (change_type IN ('CHINH_SUA', 'DOI_TEN') AND old_path IS NOT NULL AND new_path IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS DiffHunk (
    hunk_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER      NOT NULL REFERENCES ChangedFile(file_id) ON DELETE CASCADE,
    hunk_index          INTEGER      NOT NULL CHECK (hunk_index > 0),
    old_start_line      INTEGER      NOT NULL CHECK (old_start_line >= 0),
    old_line_span       INTEGER      NOT NULL CHECK (old_line_span >= 0),
    new_start_line      INTEGER      NOT NULL CHECK (new_start_line >= 0),
    new_line_span       INTEGER      NOT NULL CHECK (new_line_span >= 0),
    ast_symbol_name     VARCHAR(250) NULL,
    patch_content       TEXT         NULL,
    ast_context_snippet TEXT         NULL,
    estimated_tokens    INTEGER      NOT NULL CHECK (estimated_tokens >= 0),
    UNIQUE (file_id, hunk_index),
    UNIQUE (file_id, hunk_id)
);

CREATE TABLE IF NOT EXISTS PromptTemplate (
    prompt_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_code          VARCHAR(80)  NOT NULL,
    version_tag          VARCHAR(30)  NOT NULL,
    strategy_desc        VARCHAR(500) NOT NULL,
    system_prompt_text   TEXT         NOT NULL,
    user_prompt_template TEXT         NOT NULL,
    output_json_schema   TEXT         NOT NULL,
    prompt_hash          VARCHAR(64)  NOT NULL,
    is_active            BOOLEAN      NOT NULL CHECK (is_active IN (0, 1)),
    created_at           DATETIME     NOT NULL,
    UNIQUE (prompt_code, version_tag)
);

CREATE TABLE IF NOT EXISTS AnalysisRule (
    rule_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_source        VARCHAR(30)  NOT NULL CHECK (tool_source IN ('RUFF', 'BANDIT', 'AST_CUSTOM', 'CONVENTION')),
    rule_code          VARCHAR(60)  NOT NULL,
    rule_name          VARCHAR(200) NOT NULL,
    category           VARCHAR(40)  NOT NULL CHECK (category IN ('CHUC_NANG', 'BAO_MAT', 'HIEU_NANG', 'BAO_TRI', 'QUY_UOC')),
    default_severity   VARCHAR(20)  NOT NULL CHECK (default_severity IN ('CAO', 'TRUNG_BINH', 'THAP')),
    rule_description   TEXT         NULL,
    enabled_by_default BOOLEAN      NOT NULL CHECK (enabled_by_default IN (0, 1)),
    UNIQUE (tool_source, rule_code)
);

CREATE TABLE IF NOT EXISTS ReviewConfig (
    config_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id            INTEGER      NOT NULL REFERENCES Repository(repo_id) ON DELETE RESTRICT,
    prompt_id          INTEGER      NULL REFERENCES PromptTemplate(prompt_id) ON DELETE RESTRICT,
    version_number     INTEGER      NOT NULL CHECK (version_number > 0),
    llm_model_name     VARCHAR(100) NULL,
    temperature        DECIMAL(3,2) NULL CHECK (temperature IS NULL OR (temperature >= 0.00 AND temperature <= 2.00)),
    max_files_limit    INTEGER      NOT NULL CHECK (max_files_limit > 0),
    max_diff_lines     INTEGER      NOT NULL CHECK (max_diff_lines > 0),
    max_snapshot_bytes INTEGER      NOT NULL DEFAULT 5242880 CHECK (max_snapshot_bytes > 0),
    max_input_tokens   INTEGER      NOT NULL CHECK (max_input_tokens >= 0),
    max_output_tokens  INTEGER      NOT NULL CHECK (max_output_tokens >= 0),
    max_llm_calls      INTEGER      NOT NULL DEFAULT 6 CHECK (max_llm_calls >= 0),
    timeout_seconds    INTEGER      NOT NULL CHECK (timeout_seconds > 0),
    allow_external_llm BOOLEAN      NOT NULL DEFAULT 0 CHECK (allow_external_llm IN (0, 1)),
    auto_publish_pr    BOOLEAN      NOT NULL CHECK (auto_publish_pr IN (0, 1)),
    exclude_globs      TEXT         NULL,
    config_hash        VARCHAR(64)  NOT NULL,
    created_at         DATETIME     NOT NULL,
    UNIQUE (repo_id, version_number)
);

CREATE TABLE IF NOT EXISTS ConfigRule (
    config_id         INTEGER     NOT NULL REFERENCES ReviewConfig(config_id) ON DELETE CASCADE,
    rule_id           INTEGER     NOT NULL REFERENCES AnalysisRule(rule_id) ON DELETE RESTRICT,
    is_enabled        BOOLEAN     NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    severity_override VARCHAR(20) NULL CHECK (severity_override IS NULL OR severity_override IN ('CAO', 'TRUNG_BINH', 'THAP')),
    PRIMARY KEY (config_id, rule_id)
);

CREATE TABLE IF NOT EXISTS ReviewRun (
    run_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id             INTEGER      NOT NULL REFERENCES CodeSnapshot(snapshot_id) ON DELETE RESTRICT,
    config_id               INTEGER      NOT NULL REFERENCES ReviewConfig(config_id) ON DELETE RESTRICT,
    requested_by            INTEGER      NULL REFERENCES UserAccount(user_id) ON DELETE SET NULL,
    event_id                INTEGER      NULL UNIQUE REFERENCES WebhookEvent(event_id) ON DELETE SET NULL,
    idempotency_key         VARCHAR(128) NOT NULL UNIQUE,
    execution_mode          VARCHAR(30)  NOT NULL CHECK (execution_mode IN ('A_STATIC', 'B_LLM', 'C_NOI_KET_QUA', 'D_KET_HOP')),
    context_policy          VARCHAR(30)  NOT NULL DEFAULT 'DIFF_AST_INTENT' CHECK (context_policy IN ('DIFF_ONLY', 'DIFF_AST', 'DIFF_AST_INTENT', 'KHONG_AP_DUNG')),
    run_status              VARCHAR(30)  NOT NULL CHECK (run_status IN ('CHO_XU_LY', 'DANG_CHAY', 'HOAN_THANH', 'MOT_PHAN', 'THAT_BAI')),
    is_full_coverage        BOOLEAN      NOT NULL CHECK (is_full_coverage IN (0, 1)),
    termination_reason      VARCHAR(500) NULL,
    benchmark_sample_id     VARCHAR(100) NULL,
    benchmark_manifest_hash VARCHAR(64)  NULL,
    created_at              DATETIME     NOT NULL,
    started_at              DATETIME     NULL,
    finished_at             DATETIME     NULL,
    retention_expires_at    DATETIME     NOT NULL,
    UNIQUE (run_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS ModelInvocation (
    invocation_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER       NOT NULL REFERENCES ReviewRun(run_id) ON DELETE CASCADE,
    hunk_id             INTEGER       NULL REFERENCES DiffHunk(hunk_id) ON DELETE SET NULL,
    attempt_number      INTEGER       NOT NULL CHECK (attempt_number > 0),
    call_purpose        VARCHAR(30)   NOT NULL DEFAULT 'REVIEW' CHECK (call_purpose IN ('REVIEW', 'XAC_MINH', 'THU_LAI')),
    provider_name       VARCHAR(60)   NOT NULL,
    resolved_model_name VARCHAR(100)  NOT NULL,
    payload_hash        VARCHAR(64)   NOT NULL,
    call_status         VARCHAR(30)   NOT NULL CHECK (call_status IN ('THANH_CONG', 'QUA_HAN', 'LOI_DICH_VU', 'SAI_SCHEMA')),
    input_tokens        INTEGER       NULL CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens       INTEGER       NULL CHECK (output_tokens IS NULL OR output_tokens >= 0),
    usage_source        VARCHAR(20)   NOT NULL CHECK (usage_source IN ('THUC_TE', 'UOC_TINH', 'KHONG_CO')),
    estimated_cost_usd  DECIMAL(10,6) NULL CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
    latency_ms          INTEGER       NULL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    started_at          DATETIME      NOT NULL,
    finished_at         DATETIME      NULL,
    UNIQUE (run_id, attempt_number),
    CHECK (
        (usage_source = 'KHONG_CO' AND input_tokens IS NULL AND output_tokens IS NULL) OR
        (usage_source <> 'KHONG_CO' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS QualityAssessment (
    assessment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER     NOT NULL REFERENCES ReviewRun(run_id) ON DELETE CASCADE,
    dimension_name    VARCHAR(40) NOT NULL CHECK (dimension_name IN ('CHUC_NANG', 'BAO_MAT', 'HIEU_NANG', 'BAO_TRI', 'QUY_UOC')),
    rubric_version    VARCHAR(30) NOT NULL,
    assessment_status VARCHAR(40) NOT NULL CHECK (assessment_status IN ('CO_VAN_DE', 'CAN_XAC_MINH', 'KHONG_QUAN_SAT_THAY', 'CHUA_DU_THONG_TIN', 'KHONG_AP_DUNG')),
    is_scope_complete BOOLEAN     NOT NULL CHECK (is_scope_complete IN (0, 1)),
    summary_rationale TEXT        NOT NULL,
    UNIQUE (run_id, dimension_name)
);

CREATE TABLE IF NOT EXISTS ReviewFinding (
    finding_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  INTEGER      NOT NULL REFERENCES ReviewRun(run_id) ON DELETE CASCADE,
    snapshot_id             INTEGER      NOT NULL,
    file_id                 INTEGER      NOT NULL REFERENCES ChangedFile(file_id) ON DELETE RESTRICT,
    hunk_id                 INTEGER      NULL,
    issue_fingerprint       VARCHAR(128) NOT NULL,
    diff_side               VARCHAR(10)  NOT NULL CHECK (diff_side IN ('LEFT', 'RIGHT')),
    start_line              INTEGER      NOT NULL CHECK (start_line > 0),
    end_line                INTEGER      NOT NULL CHECK (end_line >= start_line),
    category                VARCHAR(40)  NOT NULL CHECK (category IN ('CHUC_NANG', 'BAO_MAT', 'HIEU_NANG', 'BAO_TRI', 'QUY_UOC')),
    finding_kind            VARCHAR(30)  NOT NULL CHECK (finding_kind IN ('LOI_TIEM_AN', 'GOI_Y_TOI_UU')),
    severity                VARCHAR(20)  NOT NULL CHECK (severity IN ('CAO', 'TRUNG_BINH', 'THAP')),
    evidence_status         VARCHAR(30)  NOT NULL CHECK (evidence_status IN ('CO_CAN_CU', 'CAN_XAC_MINH')),
    title                   VARCHAR(300) NOT NULL,
    explanation             TEXT         NOT NULL,
    code_evidence           TEXT         NOT NULL,
    suggested_fix           TEXT         NULL,
    fix_verification_status VARCHAR(30)  NOT NULL CHECK (fix_verification_status IN ('CHUA_KIEM_CHUNG', 'DA_KIEM_CHUNG', 'KHONG_AP_DUNG')),
    UNIQUE (run_id, issue_fingerprint),
    UNIQUE (run_id, finding_id),
    FOREIGN KEY (run_id, snapshot_id) REFERENCES ReviewRun(run_id, snapshot_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, file_id) REFERENCES ChangedFile(snapshot_id, file_id) ON DELETE RESTRICT,
    FOREIGN KEY (file_id, hunk_id) REFERENCES DiffHunk(file_id, hunk_id) ON DELETE SET NULL,
    FOREIGN KEY (run_id, category) REFERENCES QualityAssessment(run_id, dimension_name) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS FindingCandidate (
    candidate_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER      NOT NULL REFERENCES ReviewRun(run_id) ON DELETE CASCADE,
    file_id       INTEGER      NOT NULL REFERENCES ChangedFile(file_id) ON DELETE RESTRICT,
    rule_id       INTEGER      NULL REFERENCES AnalysisRule(rule_id) ON DELETE SET NULL,
    invocation_id INTEGER      NULL REFERENCES ModelInvocation(invocation_id) ON DELETE SET NULL,
    finding_id    INTEGER      NULL REFERENCES ReviewFinding(finding_id) ON DELETE SET NULL,
    source_type   VARCHAR(20)  NOT NULL CHECK (source_type IN ('RUFF', 'BANDIT', 'AST_CUSTOM', 'CONVENTION', 'LLM')),
    diff_side     VARCHAR(10)  NOT NULL CHECK (diff_side IN ('LEFT', 'RIGHT')),
    start_line    INTEGER      NOT NULL CHECK (start_line > 0),
    end_line      INTEGER      NOT NULL CHECK (end_line >= start_line),
    raw_message   TEXT         NOT NULL,
    filter_status VARCHAR(30)  NOT NULL CHECK (filter_status IN ('GIU_LAI', 'LOAI_SAI_DONG', 'LOAI_TRUNG', 'LOAI_THIEU_CAN_CU', 'LOI_CU')),
    filter_reason VARCHAR(500) NULL,
    CHECK (
        (source_type = 'LLM' AND invocation_id IS NOT NULL AND rule_id IS NULL) OR
        (source_type <> 'LLM' AND rule_id IS NOT NULL AND invocation_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS FindingFeedback (
    feedback_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id     INTEGER     NOT NULL REFERENCES ReviewFinding(finding_id) ON DELETE CASCADE,
    user_id        INTEGER     NOT NULL REFERENCES UserAccount(user_id) ON DELETE RESTRICT,
    revision_no    INTEGER     NOT NULL CHECK (revision_no > 0),
    feedback_label VARCHAR(30) NOT NULL CHECK (feedback_label IN ('DUNG', 'SAI', 'CAN_XAC_MINH')),
    reason_note    TEXT        NULL,
    created_at     DATETIME    NOT NULL,
    UNIQUE (finding_id, user_id, revision_no),
    CHECK (feedback_label <> 'SAI' OR (reason_note IS NOT NULL AND LENGTH(TRIM(reason_note)) > 0))
);

CREATE TABLE IF NOT EXISTS PublicationRecord (
    publication_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER      NOT NULL REFERENCES ReviewRun(run_id) ON DELETE CASCADE,
    finding_id          INTEGER      NULL,
    comment_scope       VARCHAR(30)  NOT NULL CHECK (comment_scope IN ('TONG_HOP_PR', 'NHAN_XET_DONG')),
    marker_key          VARCHAR(128) NOT NULL,
    target_commit_sha   VARCHAR(64)  NOT NULL,
    publish_status      VARCHAR(30)  NOT NULL CHECK (publish_status IN ('CHO_DANG', 'DA_DANG', 'BO_QUA_LOI_THOI', 'LOI_DANG', 'CAN_DOI_SOAT')),
    external_comment_id VARCHAR(100) NULL,
    retry_count         INTEGER      NOT NULL CHECK (retry_count >= 0),
    status_detail       VARCHAR(500) NULL,
    updated_at          DATETIME     NOT NULL,
    FOREIGN KEY (run_id, finding_id) REFERENCES ReviewFinding(run_id, finding_id) ON DELETE CASCADE,
    CHECK (
        (comment_scope = 'TONG_HOP_PR' AND finding_id IS NULL) OR
        (comment_scope = 'NHAN_XET_DONG' AND finding_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pub_summary ON PublicationRecord(run_id) WHERE finding_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pub_inline ON PublicationRecord(run_id, finding_id) WHERE finding_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS StorageArtifact (
    artifact_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    INTEGER      NULL REFERENCES CodeSnapshot(snapshot_id) ON DELETE SET NULL,
    run_id         INTEGER      NULL REFERENCES ReviewRun(run_id) ON DELETE SET NULL,
    artifact_type  VARCHAR(30)  NOT NULL CHECK (artifact_type IN ('RAW_SNAPSHOT', 'RAW_PROMPT', 'RAW_LLM_OUTPUT', 'REPORT_JSON', 'REPORT_MD', 'REPORT_SARIF')),
    storage_uri    VARCHAR(500) NOT NULL,
    content_sha256 VARCHAR(64)  NOT NULL,
    size_bytes     INTEGER      NOT NULL CHECK (size_bytes >= 0),
    purge_status   VARCHAR(20)  NOT NULL DEFAULT 'CON_LUU' CHECK (purge_status IN ('CON_LUU', 'DA_XOA', 'LOI_XOA')),
    expires_at     DATETIME     NOT NULL,
    purged_at      DATETIME     NULL,
    created_at     DATETIME     NOT NULL,
    CHECK (snapshot_id IS NOT NULL OR run_id IS NOT NULL),
    CHECK (purge_status <> 'DA_XOA' OR purged_at IS NOT NULL)
);
