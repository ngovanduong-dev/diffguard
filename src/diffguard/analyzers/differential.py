from __future__ import annotations

import tempfile
from pathlib import Path

from diffguard.analyzers.ast_probes import run_ast_probes_on_source
from diffguard.analyzers.bandit_adapter import run_bandit
from diffguard.analyzers.ruff_adapter import StaticToolOutput, run_ruff
from diffguard.diff import ParsedFileDiff
from diffguard.domain import FilterStatus, FindingCandidate, Severity
from diffguard.ingest import safe_resolve_under_root


def _write_snapshot_dir(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        if not rel_path.endswith((".py", ".pyi")):
            continue
        dest = safe_resolve_under_root(root, rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _run_suite_on_contents(
    files: dict[str, str],
    ruff_config: Path | None,
    bandit_config: Path | None,
    timeout_seconds: int,
) -> StaticToolOutput:
    py_files = {k: v for k, v in files.items() if k.endswith((".py", ".pyi"))}
    if not py_files:
        return StaticToolOutput()

    candidates: list[FindingCandidate] = []
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="dg_static_") as tmp:
        snap_dir = Path(tmp)
        _write_snapshot_dir(snap_dir, py_files)

        ruff_out = run_ruff(snap_dir, config_path=ruff_config, timeout_seconds=timeout_seconds)
        candidates.extend(ruff_out.candidates)
        errors.extend(ruff_out.errors)

        bandit_out = run_bandit(snap_dir, config_path=bandit_config, timeout_seconds=timeout_seconds)
        candidates.extend(bandit_out.candidates)
        errors.extend(bandit_out.errors)

    for rel_path, src in py_files.items():
        ast_out = run_ast_probes_on_source(rel_path, src)
        candidates.extend(ast_out.candidates)
        errors.extend(ast_out.errors)

    return StaticToolOutput(candidates=candidates, errors=errors)


class DifferentialStaticEngine:
    def __init__(
        self,
        ruff_config: Path | None = None,
        bandit_config: Path | None = None,
        timeout_seconds: int = 30,
        disabled_rules: set[str] | None = None,
        severity_overrides: dict[str, Severity] | None = None,
    ) -> None:
        self.ruff_config = ruff_config
        self.bandit_config = bandit_config
        self.timeout_seconds = timeout_seconds
        self.disabled_rules = disabled_rules or set()
        self.severity_overrides = severity_overrides or {}

    def analyze(
        self,
        parsed_files: list[ParsedFileDiff],
        base_contents: dict[str, str],
        head_contents: dict[str, str],
    ) -> StaticToolOutput:
        supported_paths = {pf.display_path for pf in parsed_files}
        head_subset = {k: v for k, v in head_contents.items() if k in supported_paths}
        old_paths = {pf.old_path for pf in parsed_files if pf.old_path}
        base_subset = {k: v for k, v in base_contents.items() if k in old_paths}

        head_out = _run_suite_on_contents(
            head_subset, self.ruff_config, self.bandit_config, self.timeout_seconds
        )
        base_out = _run_suite_on_contents(
            base_subset, self.ruff_config, self.bandit_config, self.timeout_seconds
        )

        pf_by_new = {pf.display_path: pf for pf in parsed_files}
        pf_by_old = {pf.old_path: pf for pf in parsed_files if pf.old_path}

        projected_base_keys: set[tuple[str, str, str, int]] = set()
        for bc in base_out.candidates:
            pf = pf_by_old.get(bc.file_path)
            if pf is None:
                continue
            new_ln = pf.project_old_line_to_new(bc.start_line)
            if new_ln is not None:
                projected_base_keys.add((pf.display_path, bc.source_type.value, bc.rule_code or "", new_ln))

        filtered: list[FindingCandidate] = []
        for hc in head_out.candidates:
            if hc.rule_code and hc.rule_code in self.disabled_rules:
                continue
            if hc.rule_code and hc.rule_code in self.severity_overrides:
                hc = hc.model_copy(update={"severity": self.severity_overrides[hc.rule_code]})

            pf = pf_by_new.get(hc.file_path)
            if pf is None:
                continue

            key = (hc.file_path, hc.source_type.value, hc.rule_code or "", hc.start_line)
            changed_lines = pf.all_changed_right_lines
            touches_diff = any(ln in changed_lines for ln in range(hc.start_line, hc.end_line + 1))

            if key in projected_base_keys and not touches_diff:
                hc = hc.model_copy(
                    update={
                        "filter_status": FilterStatus.LOI_CU,
                        "filter_reason": "Pre-existing at merge_base",
                    }
                )
            filtered.append(hc)

        return StaticToolOutput(
            candidates=filtered,
            errors=head_out.errors + base_out.errors,
        )
