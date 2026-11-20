import subprocess
from pathlib import Path

import pytest

from diffguard.domain import PatchStatus, ReviewPolicy
from diffguard.ingest import InputRejectedError, ingest_local_repo, ingest_snapshot_pair


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def test_ingest_local_repo_committed_and_uncommitted(tmp_path: Path) -> None:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.com")

    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "notes.txt").write_text("ignored text\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "buggy edit")

    res = ingest_local_repo(repo, base_ref="HEAD~1", head_ref="HEAD")
    assert res.is_empty is False
    assert res.snapshot.total_files == 2
    assert res.skipped_files == ["notes.txt"]
    assert "app.py" in res.head_contents
    assert "return a - b" in res.head_contents["app.py"]
    assert "return a + b" in res.base_contents["app.py"]

    (repo / "app.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
    wt1 = ingest_local_repo(repo, base_ref="HEAD~1", include_working_tree=True)
    assert wt1.snapshot.head_commit_sha.startswith("WT-")
    (repo / "app.py").write_text("def add(a, b):\n    return a / b\n", encoding="utf-8")
    wt2 = ingest_local_repo(repo, base_ref="HEAD~1", include_working_tree=True)
    assert wt1.snapshot.head_commit_sha != wt2.snapshot.head_commit_sha
    assert wt1.snapshot.diff_hash != wt2.snapshot.diff_hash


def test_ingest_empty_supported_changes_and_limits() -> None:
    res_empty = ingest_snapshot_pair(
        "org/demo",
        base_files={"README.md": "a\n"},
        head_files={"README.md": "b\n"},
    )
    assert res_empty.is_empty is True
    assert res_empty.snapshot.files[0].patch_status == PatchStatus.NGOAI_PHAM_VI

    with pytest.raises(InputRejectedError):
        ingest_snapshot_pair(
            "org/demo",
            base_files={"a.py": "x = 1\n", "b.py": "y = 1\n"},
            head_files={"a.py": "x = 2\n", "b.py": "y = 2\n"},
            policy=ReviewPolicy(max_files_limit=1),
        )

    with pytest.raises(InputRejectedError):
        ingest_snapshot_pair(
            "org/demo",
            base_files={"a.py": "x = 1\n"},
            head_files={"a.py": "\n".join(f"x{i} = {i}" for i in range(25))},
            policy=ReviewPolicy(max_diff_lines=10),
        )
