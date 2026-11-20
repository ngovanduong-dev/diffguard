from __future__ import annotations

import difflib
import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from diffguard.diff import ParsedFileDiff, parse_unified_diff
from diffguard.domain import ChangedFile, CodeSnapshot, InputSource, PatchStatus, ReviewPolicy


class InputRejectedError(ValueError):
    pass


@dataclass
class IngestResult:
    snapshot: CodeSnapshot
    parsed_files: list[ParsedFileDiff]
    base_contents: dict[str, str] = field(default_factory=dict)
    head_contents: dict[str, str] = field(default_factory=dict)
    skipped_files: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            cf.is_supported and cf.patch_status == PatchStatus.CO_PATCH for cf in self.snapshot.files
        )


def safe_resolve_under_root(root: Path, rel_path: str) -> Path:
    if not rel_path or "\x00" in rel_path or os.path.isabs(rel_path) or Path(rel_path).is_absolute():
        raise InputRejectedError(f"Invalid path: {rel_path}")
    root_resolved = root.resolve(strict=True)
    candidate = root_resolved / rel_path
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise InputRejectedError(f"Unresolvable path: {rel_path}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise InputRejectedError(f"Path escapes repository root: {rel_path}")
    return resolved


def _is_excluded(path: str, globs: list[str]) -> bool:
    norm = path.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pat) for pat in globs)


def _run_git(repo_dir: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _git_show_text(repo_dir: Path, rev: str, path: str) -> str | None:
    proc = _run_git(repo_dir, ["show", f"{rev}:{path}"], check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def _build_unified_diff_from_pair(base_files: dict[str, str], head_files: dict[str, str]) -> str:
    all_paths = sorted(set(base_files) | set(head_files))
    chunks: list[str] = []
    for p in all_paths:
        old_txt = base_files.get(p)
        new_txt = head_files.get(p)
        if old_txt == new_txt:
            continue
        old_lines = (old_txt or "").splitlines(keepends=True)
        new_lines = (new_txt or "").splitlines(keepends=True)
        from_file = "/dev/null" if old_txt is None else f"a/{p}"
        to_file = "/dev/null" if new_txt is None else f"b/{p}"
        header = f"diff --git a/{p} b/{p}\n"
        udiff = "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=from_file,
                tofile=to_file,
            )
        )
        if udiff:
            chunks.append(header + udiff)
    return "\n".join(chunks)


def build_ingest_result(
    repo_full_name: str,
    input_source: InputSource,
    base_sha: str,
    head_sha: str,
    merge_base_sha: str,
    diff_text: str,
    base_contents: dict[str, str],
    head_contents: dict[str, str],
    policy: ReviewPolicy | None = None,
    pr_number: int | None = None,
    pr_title: str | None = None,
    pr_description: str | None = None,
) -> IngestResult:
    pol = policy or ReviewPolicy()
    parsed = parse_unified_diff(diff_text)
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

    domain_files: list[ChangedFile] = []
    kept_parsed: list[ParsedFileDiff] = []
    skipped: list[str] = []
    supported_count = 0
    supported_diff_lines = 0
    total_snapshot_bytes = 0
    per_file_cap = 1_048_576

    for pf in parsed:
        disp = pf.display_path
        if disp and ("\x00" in disp or ".." in Path(disp).parts or os.path.isabs(disp)):
            raise InputRejectedError(f"Unsafe diff path rejected: {disp}")

        b_txt = base_contents.get(pf.old_path) if pf.old_path else None
        h_txt = head_contents.get(pf.new_path) if pf.new_path else None
        old_lc = len(b_txt.splitlines()) if b_txt is not None else 0
        new_lc = len(h_txt.splitlines()) if h_txt is not None else 0

        dom = pf.to_domain(old_line_count=old_lc, new_line_count=new_lc)
        if _is_excluded(disp, pol.exclude_globs) or not dom.is_supported:
            dom = dom.model_copy(
                update={
                    "is_supported": False,
                    "patch_status": PatchStatus.NHI_PHAN if pf.is_binary else PatchStatus.NGOAI_PHAM_VI,
                }
            )
            skipped.append(disp)
            domain_files.append(dom)
            continue

        f_bytes = len((b_txt or "").encode("utf-8")) + len((h_txt or "").encode("utf-8"))
        if (
            len((h_txt or "").encode("utf-8")) > per_file_cap
            or len((b_txt or "").encode("utf-8")) > per_file_cap
        ):
            raise InputRejectedError(f"File exceeds 1 MiB limit: {disp}")
        total_snapshot_bytes += f_bytes
        if total_snapshot_bytes > pol.max_snapshot_bytes:
            raise InputRejectedError(
                f"Snapshot size {total_snapshot_bytes} exceeds max_snapshot_bytes={pol.max_snapshot_bytes}"
            )

        supported_count += 1
        if supported_count > pol.max_files_limit:
            raise InputRejectedError(
                f"Supported file count {supported_count} exceeds max_files_limit={pol.max_files_limit}"
            )
        supported_diff_lines += pf.additions_count + pf.deletions_count
        if supported_diff_lines > pol.max_diff_lines:
            raise InputRejectedError(
                f"Changed line count {supported_diff_lines} exceeds max_diff_lines={pol.max_diff_lines}"
            )

        domain_files.append(dom)
        kept_parsed.append(pf)

    snapshot = CodeSnapshot(
        repo_full_name=repo_full_name,
        input_source=input_source,
        base_commit_sha=base_sha,
        head_commit_sha=head_sha,
        merge_base_sha=merge_base_sha,
        diff_hash=diff_hash,
        total_files=len(domain_files),
        total_additions=sum(f.additions_count for f in domain_files),
        total_deletions=sum(f.deletions_count for f in domain_files),
        files=domain_files,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_description=pr_description,
    )
    return IngestResult(
        snapshot=snapshot,
        parsed_files=kept_parsed,
        base_contents=base_contents,
        head_contents=head_contents,
        skipped_files=skipped,
    )


def ingest_snapshot_pair(
    repo_full_name: str,
    base_files: dict[str, str],
    head_files: dict[str, str],
    diff_text: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
    merge_base_sha: str | None = None,
    policy: ReviewPolicy | None = None,
    pr_number: int | None = None,
    pr_title: str | None = None,
    pr_description: str | None = None,
    input_source: InputSource = InputSource.CLI_CUC_BO,
) -> IngestResult:
    for p in set(base_files) | set(head_files):
        if "\x00" in p or ".." in Path(p).parts or os.path.isabs(p):
            raise InputRejectedError(f"Unsafe snapshot path rejected: {p}")
    effective_diff = (
        diff_text if diff_text is not None else _build_unified_diff_from_pair(base_files, head_files)
    )
    b_sha = base_sha or hashlib.sha256(str(sorted(base_files.items())).encode("utf-8")).hexdigest()
    h_sha = head_sha or hashlib.sha256(str(sorted(head_files.items())).encode("utf-8")).hexdigest()
    mb_sha = merge_base_sha or b_sha
    return build_ingest_result(
        repo_full_name=repo_full_name,
        input_source=input_source,
        base_sha=b_sha,
        head_sha=h_sha,
        merge_base_sha=mb_sha,
        diff_text=effective_diff,
        base_contents=dict(base_files),
        head_contents=dict(head_files),
        policy=policy,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_description=pr_description,
    )


def ingest_local_repo(
    repo_dir: Path,
    base_ref: str = "HEAD~1",
    head_ref: str = "HEAD",
    include_working_tree: bool = False,
    repo_full_name: str | None = None,
    policy: ReviewPolicy | None = None,
) -> IngestResult:
    root = repo_dir.resolve(strict=True)
    try:
        base_sha = _run_git(root, ["rev-parse", base_ref]).stdout.strip()
        if include_working_tree:
            head_base_sha = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
            merge_base_sha = _run_git(root, ["merge-base", base_sha, head_base_sha]).stdout.strip()
            diff_text = _run_git(root, ["diff", "--no-ext-diff", "--unified=3", merge_base_sha]).stdout
            head_sha = f"WT-{hashlib.sha256(diff_text.encode('utf-8')).hexdigest()[:12]}"
        else:
            head_sha = _run_git(root, ["rev-parse", head_ref]).stdout.strip()
            merge_base_sha = _run_git(root, ["merge-base", base_sha, head_sha]).stdout.strip()
            diff_text = _run_git(
                root, ["diff", "--no-ext-diff", "--unified=3", merge_base_sha, head_sha]
            ).stdout
    except subprocess.CalledProcessError as exc:
        raise InputRejectedError(f"Git inspection failed: {exc.stderr.strip()}") from exc

    parsed = parse_unified_diff(diff_text)
    base_contents: dict[str, str] = {}
    head_contents: dict[str, str] = {}
    for pf in parsed:
        if pf.old_path:
            safe_resolve_under_root(root, pf.old_path)
            b_txt = _git_show_text(root, merge_base_sha, pf.old_path)
            if b_txt is not None:
                base_contents[pf.old_path] = b_txt
        if pf.new_path:
            target = safe_resolve_under_root(root, pf.new_path)
            if include_working_tree:
                if target.is_file():
                    head_contents[pf.new_path] = target.read_text(encoding="utf-8", errors="replace")
            else:
                h_txt = _git_show_text(root, head_sha, pf.new_path)
                if h_txt is not None:
                    head_contents[pf.new_path] = h_txt

    name = repo_full_name or f"local/{root.name}"
    return build_ingest_result(
        repo_full_name=name,
        input_source=InputSource.CLI_CUC_BO,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base_sha,
        diff_text=diff_text,
        base_contents=base_contents,
        head_contents=head_contents,
        policy=policy,
    )
