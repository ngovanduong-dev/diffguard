# diffguard

Automated Python pull request review tool combining differential static analysis (Ruff, Bandit, Python AST probes) with bounded LLM review, deterministic AST evidence grounding, and a 5-dimension quality rubric.

## Key Capabilities

- **Differential static analysis:** Runs trusted Ruff, Bandit, and AST rules on both `merge_base` and `head` snapshots to isolate newly introduced issues from pre-existing technical debt.
- **Bounded AST context packaging:** Extracts enclosing functions, classes, imports, callee signatures, and PR intent within strict token budgets.
- **Deterministic AST grounding gate:** Verifies reported file paths, `LEFT`/`RIGHT` diff coordinates, AST symbol names, and verbatim code evidence before persisting findings.
- **Multi-format reporting & safe GitHub integration:** Outputs JSON, Markdown, and SARIF 2.1.0; enforces `head_sha` stale checks and marker-based idempotent comment publishing.
- **Reproducible evaluation harness:** Supports controlled ablation across four modes (`A_STATIC`, `B_LLM`, `C_NOI_KET_QUA`, `D_KET_HOP`) with 1-to-1 Hungarian matching and PR-clustered bootstrap confidence intervals.

## Quickstart

```bash
uv sync
uv run pytest
```
