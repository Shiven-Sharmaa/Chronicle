from __future__ import annotations

from pathlib import Path

from chronicle.config import Config, DEFAULT_EXCLUDES
from chronicle.paths import Paths, find_project_root, require_paths, NotInitializedError

import pytest


def test_config_roundtrip(tmp_path: Path):
    cfg = Config(debounce_ms=123, excludes=["a", "b"])
    path = tmp_path / "config.toml"
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded.debounce_ms == 123
    assert loaded.excludes == ["a", "b"]


def test_config_defaults_when_missing(tmp_path: Path):
    cfg = Config.load(tmp_path / "nope.toml")
    assert cfg.debounce_ms == 400
    assert cfg.excludes == DEFAULT_EXCLUDES


def test_find_project_root_walks_up(tmp_path: Path):
    root = tmp_path / "proj"
    (root / ".chronicle").mkdir(parents=True)
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == root


def test_require_paths_raises_when_not_initialized(tmp_path: Path):
    with pytest.raises(NotInitializedError):
        require_paths(tmp_path)
