"""Where ham-fleet reads and writes.

Three separate folders, so each can be synced, backed up or mounted on its own:

    <home>/
      config/            channels.yaml, radios.yaml, templates/   (hand-edited text)
      radio-downloads/   <radio id>/<date>.img: what you downloaded from each radio (input)
      output/            generated files, safe to delete

Each folder is found independently (first match wins):

    config     --config     $HAM_FLEET_CONFIG     <home>/config
    downloads  --downloads  $HAM_FLEET_DOWNLOADS  radios.yaml paths.downloads  <home>/radio-downloads
    output     --output     $HAM_FLEET_OUTPUT     radios.yaml paths.output     <home>/output
    home       --home       $HAM_FLEET_HOME       ./my-fleet   <repo>/my-fleet   <repo>/examples/demo

In Docker, mount the three folders at /config, /radio-downloads and /output.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    home: Optional[Path]
    config: Path
    downloads: Path
    output: Path

    @property
    def templates(self) -> Path:
        return self.config / "templates"

    @property
    def channels_file(self) -> Path:
        return self.config / "channels.yaml"

    @property
    def radios_file(self) -> Path:
        return self.config / "radios.yaml"


def _p(s) -> Path:
    return Path(s).expanduser().resolve()


def find_home(home: Optional[str] = None) -> Path:
    if home or os.environ.get("HAM_FLEET_HOME"):
        return _p(home or os.environ["HAM_FLEET_HOME"])
    for cand in (Path.cwd() / "my-fleet", ROOT / "my-fleet"):
        if (cand / "config" / "channels.yaml").exists():
            return cand.resolve()
    return ROOT / "examples" / "demo"


def resolve(home=None, config=None, downloads=None, output=None, file_paths: Optional[dict] = None) -> Paths:
    """Work out the three folders. file_paths is the optional `paths:` block from radios.yaml."""
    h = find_home(home)
    cfg = _p(config or os.environ.get("HAM_FLEET_CONFIG") or h / "config")
    fp = file_paths or {}

    def pick(cli, env, key, default):
        if cli:
            return _p(cli)
        if os.environ.get(env):
            return _p(os.environ[env])
        if fp.get(key):
            v = Path(str(fp[key])).expanduser()
            return v if v.is_absolute() else (h / v).resolve()
        return default

    return Paths(home=h, config=cfg,
                 downloads=pick(downloads, "HAM_FLEET_DOWNLOADS", "downloads", h / "radio-downloads"),
                 output=pick(output, "HAM_FLEET_OUTPUT", "output", h / "output"))
