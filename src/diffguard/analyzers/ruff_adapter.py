from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from diffguard.domain import Category, DiffSide, FindingCandidate, Severity, SourceType

DEFAULT_RUFF_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "ruff.toml"


@dataclass
class StaticToolOutput:
    candidates: list[FindingCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _map_ruff_category(code: str) -> tuple[Category, Severity]:
    if code.startswith("S"):
        return Category.BAO_MAT, Severity.CAO
    if code.startswith("PERF"):
        return Category.HIEU_NANG, Severity.TRUNG_BINH
    if code.startswith(("F", "B", "E7", "E9")):
        return Category.CHUC_NANG, Severity.TRUNG_BINH
    if code.startswith("SIM"):
        return Category.BAO_TRI, Severity.THAP
    return Category.QUY_UOC, Severity.THAP


def run_ruff(
    snapshot_dir: Path,
    config_path: Path | None = None,
    timeout_seconds: int = 30,
) -> StaticToolOutput:
    cfg = config_path or DEFAULT_RUFF_CONFIG
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--output-format",
        "json",
        "--no-cache",
        "--config",
        str(cfg),
        ".",
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
        return StaticToolOutput(errors=[f"ruff timed out after {timeout_seconds}s"])
    except OSError as exc:
        return StaticToolOutput(errors=[f"ruff execution error: {exc}"])

    if proc.returncode not in (0, 1):
        msg = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        return StaticToolOutput(errors=[f"ruff failed: {msg}"])

    if not proc.stdout.strip():
        return StaticToolOutput()

    try:
        raw_items = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return StaticToolOutput(errors=[f"ruff invalid JSON: {exc}"])
    if not isinstance(raw_items, list):
        return StaticToolOutput(errors=["ruff unexpected JSON root type"])

    candidates: list[FindingCandidate] = []
    root_res = snapshot_dir.resolve()
    for item in raw_items:
        code = str(item.get("code") or "RUFF")
        fpath_raw = str(item.get("filename") or "")
        try:
            rel = Path(fpath_raw).resolve().relative_to(root_res).as_posix()
        except ValueError:
            rel = Path(fpath_raw).as_posix()
        loc = item.get("location") or {}
        end_loc = item.get("end_location") or loc
        start_ln = max(1, int(loc.get("row") or 1))
        end_ln = max(start_ln, int(end_loc.get("row") or start_ln))
        msg = str(item.get("message") or code)
        cat, sev = _map_ruff_category(code)
        candidates.append(
            FindingCandidate(
                file_path=rel,
                source_type=SourceType.RUFF,
                diff_side=DiffSide.RIGHT,
                start_line=start_ln,
                end_line=end_ln,
                category=cat,
                severity=sev,
                title=f"[{code}] {msg}"[:280],
                raw_message=msg,
                rule_code=code,
            )
        )
    return StaticToolOutput(candidates=candidates)
