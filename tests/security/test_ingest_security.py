import os
from pathlib import Path

import pytest

from diffguard.domain import ReviewPolicy
from diffguard.ingest import InputRejectedError, ingest_snapshot_pair, safe_resolve_under_root


def test_path_traversal_rejected_in_root_resolver(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP_SECRET", encoding="utf-8")

    with pytest.raises(InputRejectedError):
        safe_resolve_under_root(root, "../secret.txt")
    with pytest.raises(InputRejectedError):
        safe_resolve_under_root(root, "/etc/passwd")
    with pytest.raises(InputRejectedError):
        safe_resolve_under_root(root, "sub/../../secret.txt")


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("API_KEY = 'secret'", encoding="utf-8")
    link = root / "leak.py"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on this Windows host")
    with pytest.raises(InputRejectedError):
        safe_resolve_under_root(root, "leak.py")


def test_snapshot_pair_rejects_traversal_and_oversized_file() -> None:
    with pytest.raises(InputRejectedError):
        ingest_snapshot_pair(
            "org/demo",
            base_files={"../../evil.py": "x = 1\n"},
            head_files={"../../evil.py": "x = 2\n"},
        )
    huge = "x = 1\n" * 200_000
    with pytest.raises(InputRejectedError):
        ingest_snapshot_pair(
            "org/demo",
            base_files={"big.py": "x = 0\n"},
            head_files={"big.py": huge},
            policy=ReviewPolicy(max_snapshot_bytes=10_000_000),
        )
