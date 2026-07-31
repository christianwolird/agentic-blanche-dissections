"""Reproducibility manifests for search and benchmark runs."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from agentic_blanche import __version__


def _command_output(command: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).strip()
    return text.splitlines()[0] if text else None


def _git_commit(directory: Path) -> str | None:
    return _command_output(("git", "-C", str(directory), "rev-parse", "HEAD"))


def create_manifest(
    *,
    argv: Sequence[str],
    config: Mapping[str, object],
    repository: Path,
    plantri: str,
    msolve: str,
) -> dict[str, object]:
    """Capture enough environment data to reproduce one search."""
    created_at = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "schema_version": 1,
        "created_at": created_at,
        "argv": list(argv),
        "config": dict(config),
        "repository_commit": _git_commit(repository),
        "agentic_blanche_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "plantri": {
            "path": plantri,
            "version": _command_output((plantri, "-help")),
        },
        "msolve": {
            "path": msolve,
            "version": _command_output((msolve, "--version")),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["run_id"] = hashlib.sha256(canonical).hexdigest()[:24]
    return payload
