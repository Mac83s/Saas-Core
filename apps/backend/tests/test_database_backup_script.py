"""The backup script's two promises that nothing else would notice breaking.

`infra/postgres/backup.sh check` is what a deployment session and, later,
monitoring ask: its first word and exit code are the contract. `rotate` is the
only part of the script that deletes. Neither needs a database or Docker, so
both are pinned here on files in a temporary directory.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "backup.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("sha256sum") is None or shutil.which("sh") is None,
    reason="the script needs a POSIX shell and GNU coreutils",
)


def _dump(directory: Path, stack: str, taken: datetime, *, checksum: bool = True) -> Path:
    path = directory / f"{stack}-{taken:%Y%m%dT%H%M%SZ}.dump"
    path.write_bytes(f"archive of {stack} at {taken.isoformat()}".encode())
    if checksum:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (directory / f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n")
    return path


def _script(
    directory: Path, *arguments: str, **environment: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), *arguments],
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "BACKUP_DIR": str(directory), **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_reports_a_missing_backup(tmp_path: Path) -> None:
    _dump(tmp_path, "hoofcare", datetime.now(UTC))

    result = _script(tmp_path, "check", "saas-core")

    assert result.returncode == 2
    assert result.stdout.startswith("MISSING saas-core:")


def test_check_accepts_a_fresh_dump_and_refuses_an_old_one(tmp_path: Path) -> None:
    newest = _dump(tmp_path, "saas-core", datetime.now(UTC) - timedelta(hours=3, minutes=5))

    fresh = _script(tmp_path, "check", "saas-core")
    stale = _script(tmp_path, "check", "saas-core", BACKUP_MAX_AGE_HOURS="3")

    assert fresh.returncode == 0
    assert fresh.stdout.startswith(f"OK saas-core: newest good dump {newest.name}, 3 h ")
    assert stale.returncode == 1
    assert stale.stdout.startswith("STALE saas-core:")


def test_check_counts_only_finished_dumps_whose_checksum_holds(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    good = _dump(tmp_path, "saas-core", now - timedelta(hours=30))
    damaged = _dump(tmp_path, "saas-core", now - timedelta(hours=2))
    damaged.write_bytes(damaged.read_bytes()[:-5])
    _dump(tmp_path, "saas-core", now - timedelta(hours=1), checksum=False)
    (tmp_path / f"saas-core-{now:%Y%m%dT%H%M%SZ}.dump.partial").write_bytes(b"half")

    result = _script(tmp_path, "check", "saas-core")

    assert result.returncode == 1
    assert result.stdout.startswith(f"STALE saas-core: newest good dump {good.name}, 30 h ")
    assert result.stderr.count("skipped") == 2


def test_rotation_keeps_seven_days_and_four_weeks(tmp_path: Path) -> None:
    last = datetime(2026, 10, 6, 2, 30, tzinfo=UTC)  # a Tuesday, ISO week 41
    for back in range(40):
        _dump(tmp_path, "saas-core", last - timedelta(days=back))
    _dump(tmp_path, "saas-core", datetime(2026, 10, 3, 15, 0, tzinfo=UTC))
    other = _dump(tmp_path, "hoofcare", datetime(2026, 8, 1, 2, 30, tzinfo=UTC))

    result = _script(tmp_path, "rotate", "saas-core")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "31"
    kept = sorted(path.name for path in tmp_path.glob("saas-core-*.dump"))
    assert kept == [
        # the last dump of ISO weeks 38 and 39, beyond the seven days
        "saas-core-20260920T023000Z.dump",
        "saas-core-20260927T023000Z.dump",
        # every dump of the seven newest days, both of 3 October among them
        "saas-core-20260930T023000Z.dump",
        "saas-core-20261001T023000Z.dump",
        "saas-core-20261002T023000Z.dump",
        "saas-core-20261003T023000Z.dump",
        "saas-core-20261003T150000Z.dump",
        "saas-core-20261004T023000Z.dump",
        "saas-core-20261005T023000Z.dump",
        "saas-core-20261006T023000Z.dump",
    ]
    checksums = sorted(path.name for path in tmp_path.glob("saas-core-*.sha256"))
    assert checksums == [f"{name}.sha256" for name in kept]
    assert other.exists()
