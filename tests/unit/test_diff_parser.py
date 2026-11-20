from diffguard.diff import parse_unified_diff
from diffguard.domain import ChangeType, PatchStatus


def test_empty_and_whitespace_diff() -> None:
    assert parse_unified_diff("") == []
    assert parse_unified_diff("   \n\r\n  ") == []


def test_single_file_modify_multi_hunk_and_projection() -> None:
    diff = (
        "diff --git a/app/calc.py b/app/calc.py\n"
        "--- a/app/calc.py\n"
        "+++ b/app/calc.py\n"
        "@@ -1,4 +1,5 @@\n"
        " def add(a, b):\n"
        "+    if a is None:\n"
        "+        return 0\n"
        "-    return a + b\n"
        "+    return a + b\n"
        " \n"
        "@@ -10,3 +11,2 @@ def sub(x, y):\n"
        " def sub(x, y):\n"
        "-    tmp = x - y\n"
        "-    return tmp\n"
        "+    return x - y\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    f = files[0]
    assert f.change_type == ChangeType.CHINH_SUA
    assert len(f.hunks) == 2
    assert f.additions_count == 4
    assert f.deletions_count == 3
    assert f.hunks[0].added_lines == {2, 3, 4}
    assert f.hunks[0].deleted_lines == {2}
    assert f.hunks[1].header_context == "def sub(x, y):"
    assert f.project_old_line_to_new(1) == 1
    assert f.project_old_line_to_new(2) is None
    assert f.project_old_line_to_new(10) == 11
    assert f.project_old_line_to_new(20) == 20


def test_new_file_single_line_omitted_span_and_no_newline() -> None:
    diff = (
        "diff --git a/hello.py b/hello.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/hello.py\n"
        "@@ -0,0 +1 @@\n"
        "+print('xin chào')\n"
        "\\ No newline at end of file\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    f = files[0]
    assert f.change_type == ChangeType.THEM_MOI
    assert f.old_path is None
    assert f.new_path == "hello.py"
    assert f.hunks[0].added_lines == {1}
    assert f.additions_count == 1
    assert f.deletions_count == 0


def test_pure_deletion_and_domain_conversion() -> None:
    diff = (
        "diff --git a/legacy.py b/legacy.py\n"
        "deleted file mode 100644\n"
        "--- a/legacy.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-x = 1\n"
        "-y = 2\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    f = files[0]
    assert f.change_type == ChangeType.XOA
    assert f.new_path is None
    assert f.all_changed_left_lines == {1, 2}
    assert f.project_old_line_to_new(1) is None
    dom = f.to_domain(old_line_count=2, new_line_count=0)
    assert dom.is_supported is True
    assert dom.change_type == ChangeType.XOA


def test_pure_rename_zero_hunks_and_binary_file() -> None:
    diff = (
        "diff --git a/old_mod.py b/new_mod.py\n"
        "similarity index 100%\n"
        "rename from old_mod.py\n"
        "rename to new_mod.py\n"
        "diff --git a/img/logo.png b/img/logo.png\n"
        "Binary files a/img/logo.png and b/img/logo.png differ\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 2
    assert files[0].change_type == ChangeType.DOI_TEN
    assert files[0].old_path == "old_mod.py"
    assert files[0].new_path == "new_mod.py"
    assert files[0].hunks == []
    assert files[1].is_binary is True
    assert files[1].patch_status == PatchStatus.NHI_PHAN
    assert files[1].to_domain().is_supported is False


def test_crlf_and_unicode_plain_unified_diff() -> None:
    diff = (
        "--- a/tệp_mẫu.py\r\n+++ b/tệp_mẫu.py\r\n@@ -1,2 +1,2 @@\r\n-msg = 'cũ'\r\n+msg = 'mới'\r\n pass\r\n"
    )
    files = parse_unified_diff(diff)
    assert len(files) == 1
    assert files[0].display_path == "tệp_mẫu.py"
    assert files[0].hunks[0].added_lines == {1}
    assert files[0].hunks[0].deleted_lines == {1}
    assert files[0].project_old_line_to_new(2) == 2
