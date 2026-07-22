import re
import subprocess
from pathlib import Path


LEGACY_PRODUCT_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9])" + "chat" + r"[_-]?" + "api" + r"(?![a-z0-9])"
)


def test_tracked_files_do_not_contain_legacy_product_identifiers() -> None:
    repository = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout.decode().split("\0")
    matches: list[str] = []
    for relative in filter(None, tracked):
        text = (repository / relative).read_bytes().decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            if LEGACY_PRODUCT_PATTERN.search(line):
                matches.append(f"{relative}:{line_number}:{line.strip()}")

    assert matches == []
