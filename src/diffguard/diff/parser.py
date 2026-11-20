from __future__ import annotations

import re
from dataclasses import dataclass, field

from diffguard.domain import ChangedFile, ChangeType, DiffHunk, PatchStatus

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:\s*(.*))?$")
DIFF_GIT_RE = re.compile(r'^diff --git (?:"?a/(.+?)"?|a/(\S+)) (?:"?b/(.+?)"?|b/(\S+))$')


def _strip_diff_prefix(raw: str, expected_prefix: str) -> str:
    s = raw.strip()
    if s.startswith('"') and s.endswith('"'):
        s = bytes(s[1:-1], "utf-8").decode("unicode_escape")
    if s.startswith(expected_prefix):
        return s[len(expected_prefix) :]
    return s


def _detect_language(path: str) -> str:
    low = path.lower()
    if low.endswith((".py", ".pyi")):
        return "Python"
    if low.endswith((".js", ".jsx", ".ts", ".tsx")):
        return "JavaScript/TypeScript"
    if low.endswith((".md", ".rst", ".txt")):
        return "Text"
    if low.endswith((".yml", ".yaml", ".json", ".toml")):
        return "Config"
    return "Other"


@dataclass
class ParsedHunk:
    hunk_index: int
    old_start_line: int
    old_line_span: int
    new_start_line: int
    new_line_span: int
    header_context: str | None
    patch_content: str
    added_lines: set[int] = field(default_factory=set)
    deleted_lines: set[int] = field(default_factory=set)
    left_lines: set[int] = field(default_factory=set)
    right_lines: set[int] = field(default_factory=set)
    old_to_new_context: dict[int, int] = field(default_factory=dict)

    def to_domain(self) -> DiffHunk:
        est = max(1, len(self.patch_content) // 4)
        return DiffHunk(
            hunk_index=self.hunk_index,
            old_start_line=self.old_start_line,
            old_line_span=self.old_line_span,
            new_start_line=self.new_start_line,
            new_line_span=self.new_line_span,
            ast_symbol_name=self.header_context or None,
            patch_content=self.patch_content,
            estimated_tokens=est,
        )


@dataclass
class ParsedFileDiff:
    old_path: str | None
    new_path: str | None
    change_type: ChangeType
    patch_status: PatchStatus = PatchStatus.CO_PATCH
    hunks: list[ParsedHunk] = field(default_factory=list)
    additions_count: int = 0
    deletions_count: int = 0
    is_binary: bool = False

    @property
    def display_path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def all_changed_right_lines(self) -> set[int]:
        out: set[int] = set()
        for h in self.hunks:
            out.update(h.added_lines)
        return out

    @property
    def all_changed_left_lines(self) -> set[int]:
        out: set[int] = set()
        for h in self.hunks:
            out.update(h.deleted_lines)
        return out

    def project_old_line_to_new(self, old_line: int) -> int | None:
        if self.change_type == ChangeType.XOA:
            return None
        delta = 0
        for h in self.hunks:
            if old_line in h.deleted_lines:
                return None
            if old_line in h.old_to_new_context:
                return h.old_to_new_context[old_line]
            h_old_end = h.old_start_line + max(h.old_line_span, 1) - 1
            if old_line > h_old_end:
                delta += h.new_line_span - h.old_line_span
            elif h.old_start_line <= old_line <= h_old_end:
                return None
        return max(1, old_line + delta)

    def to_domain(self, old_line_count: int = 0, new_line_count: int = 0) -> ChangedFile:
        lang = "Binary" if self.is_binary else _detect_language(self.display_path)
        supported = (not self.is_binary) and lang == "Python"
        return ChangedFile(
            old_path=self.old_path,
            new_path=self.new_path,
            change_type=self.change_type,
            patch_status=PatchStatus.NHI_PHAN if self.is_binary else self.patch_status,
            language=lang,
            old_line_count=old_line_count,
            new_line_count=new_line_count,
            additions_count=self.additions_count,
            deletions_count=self.deletions_count,
            is_supported=supported,
            hunks=[h.to_domain() for h in self.hunks],
        )


def parse_unified_diff(diff_text: str) -> list[ParsedFileDiff]:
    normalized = diff_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return []
    lines = normalized.split("\n")
    files: list[ParsedFileDiff] = []

    idx = 0
    n = len(lines)
    while idx < n:
        ln = lines[idx]
        if ln.startswith("diff --git "):
            m = DIFF_GIT_RE.match(ln)
            a_cand = (m.group(1) or m.group(2)) if m else None
            b_cand = (m.group(3) or m.group(4)) if m else None
            idx += 1
            block_end = idx
            while block_end < n and not lines[block_end].startswith("diff --git "):
                block_end += 1
            parsed = _parse_file_block(lines[idx:block_end], a_cand, b_cand)
            if parsed is not None:
                files.append(parsed)
            idx = block_end
        elif ln.startswith("--- "):
            block_end = idx + 1
            while block_end < n and not lines[block_end].startswith(("diff --git ", "--- ")):
                block_end += 1
            parsed = _parse_file_block(lines[idx:block_end], None, None)
            if parsed is not None:
                files.append(parsed)
            idx = block_end
        else:
            idx += 1
    return files


def _parse_file_block(
    block: list[str],
    header_a: str | None,
    header_b: str | None,
) -> ParsedFileDiff | None:
    old_path = header_a
    new_path = header_b
    rename_from: str | None = None
    rename_to: str | None = None
    is_new = False
    is_del = False
    is_bin = False
    hunks: list[ParsedHunk] = []
    total_add = 0
    total_del = 0

    i = 0
    m = len(block)
    while i < m:
        ln = block[i]
        if ln.startswith("new file mode"):
            is_new = True
        elif ln.startswith("deleted file mode"):
            is_del = True
        elif ln.startswith("rename from "):
            rename_from = ln[len("rename from ") :].strip()
        elif ln.startswith("rename to "):
            rename_to = ln[len("rename to ") :].strip()
        elif ln.startswith("Binary files ") or ln == "GIT binary patch":
            is_bin = True
        elif ln.startswith("--- "):
            raw_old = ln[4:].split("\t", 1)[0].strip()
            if raw_old == "/dev/null":
                is_new = True
                old_path = None
            else:
                old_path = _strip_diff_prefix(raw_old, "a/")
        elif ln.startswith("+++ "):
            raw_new = ln[4:].split("\t", 1)[0].strip()
            if raw_new == "/dev/null":
                is_del = True
                new_path = None
            else:
                new_path = _strip_diff_prefix(raw_new, "b/")
        elif ln.startswith("@@ "):
            hm = HUNK_RE.match(ln)
            if hm:
                old_start = int(hm.group(1))
                old_span = int(hm.group(2)) if hm.group(2) is not None else 1
                new_start = int(hm.group(3))
                new_span = int(hm.group(4)) if hm.group(4) is not None else 1
                ctx = (hm.group(5) or "").strip() or None

                hunk_lines = [ln]
                added: set[int] = set()
                deleted: set[int] = set()
                left_set: set[int] = set()
                right_set: set[int] = set()
                ctx_map: dict[int, int] = {}
                cur_old = old_start
                cur_new = new_start
                j = i + 1
                while j < m:
                    hl = block[j]
                    if hl.startswith(("@@ ", "diff --git ", "--- ")):
                        break
                    if hl.startswith("\\ No newline at end of file"):
                        hunk_lines.append(hl)
                        j += 1
                        continue
                    if hl.startswith("+"):
                        added.add(cur_new)
                        right_set.add(cur_new)
                        cur_new += 1
                        total_add += 1
                        hunk_lines.append(hl)
                    elif hl.startswith("-"):
                        deleted.add(cur_old)
                        left_set.add(cur_old)
                        cur_old += 1
                        total_del += 1
                        hunk_lines.append(hl)
                    elif hl.startswith(" ") or hl == "":
                        if hl == "" and j == m - 1:
                            j += 1
                            continue
                        left_set.add(cur_old)
                        right_set.add(cur_new)
                        ctx_map[cur_old] = cur_new
                        cur_old += 1
                        cur_new += 1
                        hunk_lines.append(hl)
                    else:
                        break
                    j += 1

                hunks.append(
                    ParsedHunk(
                        hunk_index=len(hunks) + 1,
                        old_start_line=old_start,
                        old_line_span=old_span,
                        new_start_line=new_start,
                        new_line_span=new_span,
                        header_context=ctx,
                        patch_content="\n".join(hunk_lines),
                        added_lines=added,
                        deleted_lines=deleted,
                        left_lines=left_set,
                        right_lines=right_set,
                        old_to_new_context=ctx_map,
                    )
                )
                i = j
                continue
        i += 1

    if rename_from is not None and rename_to is not None:
        change_type = ChangeType.DOI_TEN
        old_path = rename_from
        new_path = rename_to
    elif is_new or old_path is None:
        change_type = ChangeType.THEM_MOI
        old_path = None
    elif is_del or new_path is None:
        change_type = ChangeType.XOA
        new_path = None
    elif old_path != new_path:
        change_type = ChangeType.DOI_TEN
    else:
        change_type = ChangeType.CHINH_SUA

    if old_path is None and new_path is None:
        return None

    return ParsedFileDiff(
        old_path=old_path,
        new_path=new_path,
        change_type=change_type,
        patch_status=PatchStatus.NHI_PHAN if is_bin else PatchStatus.CO_PATCH,
        hunks=hunks,
        additions_count=total_add,
        deletions_count=total_del,
        is_binary=is_bin,
    )
