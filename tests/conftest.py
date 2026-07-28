from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chronicle.config import Config
from chronicle.db import init_db
from chronicle.engine import SnapshotEngine
from chronicle.paths import Paths
from chronicle.store import ShadowStore


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A bare project dir with a real .git (so gitignore filtering is exercised)."""
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    (root / ".gitignore").write_text("*.log\nbuild/\n")
    return root


@pytest.fixture
def initialized(project: Path) -> Paths:
    paths = Paths.for_root(project)
    paths.chronicle_dir.mkdir(parents=True)
    config = Config(debounce_ms=50, max_batch_window_s=1.0)
    config.save(paths.config_path)
    store = ShadowStore(paths.store_dir, paths.root)
    store.init(config.excludes)
    init_db(paths.db_path)
    return paths


@pytest.fixture
def engine(initialized: Paths) -> SnapshotEngine:
    return SnapshotEngine(initialized)
