from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from diffguard.analyzers.ruff_adapter import StaticToolOutput
from diffguard.domain import Category, DiffSide, FindingCandidate, Severity, SourceType

DEFAULT_BANDIT_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "bandit.yaml"


def _map_bandit_severity(raw_sev: str) -> Severity:
    up = raw_sev.upper()
    if up == "HIGH":
        return Severity.CAO
    if up == "MEDIUM":
        return Severity.TRUNG_BINH
    return Severity.THAP


def run_bandit(
    snapshot_dir: Path,
    config_path: Path | None = None,
    timeout_seconds: int = 30,
) -> StaticToolOutput:
    cfg = config_path or DEFAULT_BANDIT_CONFIG
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        ".",
        "-f",
        "json",
        "-c",
        str(cfg),
        "-q",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(snapshot_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return StaticToolOutput(errors=[f"bandit timed out after {timeout_seconds}s"])
    except OSError as exc:
        return StaticToolOutput(errors=[f"bandit execution error: {exc}"])

    if proc.returncode not in (0, 1):
        msg = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        return StaticToolOutput(errors=[f"bandit failed: {msg}"])

    if not proc.stdout.strip():
        return StaticToolOutput()

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return StaticToolOutput(errors=[f"bandit invalid JSON: {exc}"])

    results = payload.get("results", [])
    if not isinstance(results, list):
        return StaticToolOutput(errors=["bandit unexpected results format"])

    candidates: list[FindingCandidate] = []
    root_res = snapshot_dir.resolve()
    for item in results:
        code = str(item.get("test_id") or "BANDIT")
        fpath_raw = str(item.get("filename") or "")
        try:
            rel = Path(fpath_raw).resolve().relative_to(root_res).as_posix()
        except ValueError:
            rel = Path(fpath_raw).as_posix().lstrip("./")
        start_ln = max(1, int(item.get("line_number") or 1))
        line_range = item.get("line_range") or [start_ln]
        end_ln = max(start_ln, max(int(x) for x in line_range))
        msg = str(item.get("issue_text") or code)
        sev = _map_bandit_severity(str(item.get("issue_severity") or "MEDIUM"))
        candidates.append(
            FindingCandidate(
                file_path=rel,
                source_type=SourceType.BANDIT,
                diff_side=DiffSide.RIGHT,
                start_line=start_ln,
                end_line=end_ln,
                category=Category.BAO_MAT,
                severity=sev,
                title=f"[{code}] {msg}"[:280],
                raw_message=msg,
                code_evidence=str(item.get("code") or ""),
                rule_code=code,
            )
        )
    return StaticToolOutput(candidates=candidates)
