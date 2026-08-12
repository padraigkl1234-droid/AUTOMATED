"""Config + environment loading.

Every module reads settings through here so that tests can point the whole
pipeline at a fixture directory with one argument.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class ConfigError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    """Load config/<name>.yaml. Cached -- config does not change mid-run."""
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(f"missing config file: {path}")
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and not val:
        raise ConfigError(
            f"{key} is not set. Copy .env.example to .env and fill it in."
        )
    return val or ""


@dataclass(frozen=True)
class PublishMode:
    """Three-position safety switch, read from PUBLISH_MODE.

    never  -- render only, touch no network. The default for local runs.
    drafts -- render and write to the review queue for a human to approve.
    auto   -- publish straight through. Only flip this once you have watched
              the queue produce output you would have posted yourself.
    """

    value: str

    @property
    def renders(self) -> bool:
        return True

    @property
    def queues(self) -> bool:
        return self.value in ("drafts", "auto")

    @property
    def publishes(self) -> bool:
        return self.value == "auto"


def publish_mode() -> PublishMode:
    val = env("PUBLISH_MODE", "never").strip().lower()
    if val not in ("never", "drafts", "auto"):
        raise ConfigError(
            f"PUBLISH_MODE must be never|drafts|auto, got {val!r}"
        )
    return PublishMode(val)


def out_dir() -> Path:
    d = Path(env("MEDIA_UPLOAD_DIR", "./out"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir() -> Path:
    d = ROOT / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d
