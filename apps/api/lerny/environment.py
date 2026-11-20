"""Read private configuration without exporting secrets into child processes."""
import os
from pathlib import Path

from dotenv import dotenv_values


def runtime_root():
    if root := os.environ.get("LERNY_RUNTIME_ROOT"):
        return Path(root)
    private = Path.home() / "LernyPrivateData"
    if not cloud_environment() and (private / "secrets/app.json").is_file():
        return private
    return Path.home() / "LernyData"


def cloud_environment():
    return os.environ.get("VERCEL") == "1" or os.environ.get("LERNY_DEPLOYMENT") == "cloud"


def private_env_path(root=None):
    return Path(os.environ.get("LERNY_ENV_FILE", (root or runtime_root()) / "secrets/team.env"))


def read_env(path=None):
    # A deployed service uses its own environment; never reads a developer's private file.
    if cloud_environment() and path is None:
        return {}
    source = Path(path) if path is not None else private_env_path()
    if not source.is_file():
        return {}
    return {k: v for k, v in dotenv_values(source, encoding="utf-8-sig", interpolate=False).items()
            if v is not None and v != ""}
