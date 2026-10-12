"""Channel plan and fleet config: loading and data classes."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

if TYPE_CHECKING:
    from .paths import Paths

TONE_MODES = ("", "Tone", "TSQL", "DTCS")
MODES = ("FM", "NFM", "AM")
POWERS = ("High", "Low")


@dataclass
class Channel:
    ch: int
    name: str
    short: str
    freq: float
    group: str                 # group id
    group_title: str
    tier: str = "core"
    duplex: str = ""           # "", "+", "-"
    offset: float = 0.0
    tone_mode: str = ""
    tone: float = 88.5
    dcs: int = 23
    mode: str = "FM"
    power: str = "High"
    rx_only: bool = False
    scan_skip: bool = False
    note: str = ""

    @property
    def tx_freq(self) -> float:
        if self.duplex == "+":
            return round(self.freq + self.offset, 5)
        if self.duplex == "-":
            return round(self.freq - self.offset, 5)
        return self.freq

    @property
    def is_repeater(self) -> bool:
        return self.duplex in ("+", "-")


@dataclass
class Group:
    id: str
    title: str
    tier: str = "core"
    card: str = "table"
    dm32_zone: Optional[str] = None
    channels: list[Channel] = field(default_factory=list)


@dataclass
class Plan:
    groups: list[Group]

    @property
    def channels(self) -> list[Channel]:
        return [c for g in self.groups for c in g.channels]

    def group(self, gid: str) -> Group:
        for g in self.groups:
            if g.id == gid:
                return g
        raise KeyError(gid)


def load_plan(path: Path) -> Plan:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    groups = []
    for g in data["groups"]:
        grp = Group(id=g["id"], title=g["title"], tier=g.get("tier", "core"),
                    card=g.get("card", "table"), dm32_zone=g.get("dm32_zone"))
        for c in g.get("channels", []):
            grp.channels.append(Channel(
                ch=int(c["ch"]), name=str(c["name"]), short=str(c.get("short", c["name"][:7])),
                freq=float(c["freq"]), group=grp.id, group_title=grp.title, tier=grp.tier,
                duplex=str(c.get("duplex", "")), offset=float(c.get("offset", 0.0)),
                tone_mode=str(c.get("tone_mode", "")), tone=float(c.get("tone", 88.5)),
                dcs=int(c.get("dcs", 23)), mode=str(c.get("mode", "FM")),
                power=str(c.get("power", "High")), rx_only=bool(c.get("rx_only", False)),
                scan_skip=bool(c.get("scan_skip", False)), note=str(c.get("note", "")),
            ))
        groups.append(grp)
    return Plan(groups)


@dataclass
class RadioDef:
    id: str
    label: str
    kind: str
    output: str
    tiers: list[str]
    base: Optional[str] = None
    groups: Optional[list[str]] = None
    remap: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)
    extra: Optional[dict] = None
    template_channel: Optional[str] = None
    settings: dict = field(default_factory=dict)


BASE_EXT = {"chirp-image": ".img", "neonplug": ".neonplug"}


@dataclass
class Fleet:
    paths: "Paths"
    radios: list[RadioDef]
    card_subtitle: str = ""
    operator: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)

    @property
    def output_dir(self) -> Path:
        return self.paths.output

    def radio_out(self, radio: "RadioDef") -> Path:
        """Each radio's files go in their own folder: output/<radio id>/"""
        return self.paths.output / radio.id

    @property
    def cards_out(self) -> Path:
        return self.paths.output / "cards"

    def radio_downloads(self, radio: "RadioDef") -> Path:
        return self.paths.downloads / radio.id

    def extra_file(self, radio: "RadioDef") -> Optional[Path]:
        if radio.extra and radio.extra.get("from_image"):
            return self.radio_downloads(radio) / radio.extra["from_image"]
        return None

    def base_file(self, radio: "RadioDef") -> Optional[Path]:
        """The download a build starts from: radio-downloads/<id>/<base> if pinned, else the latest one.

        "Latest" means last by file name, so date-named files (2026-10-11.img) sort correctly and the
        choice doesn't change when a sync or copy resets file times.

        Returns None if the radio needs no image (chirp-csv) or none has been saved yet.
        """
        ext = BASE_EXT.get(radio.kind)
        if not ext:
            return None
        d = self.radio_downloads(radio)
        if radio.base:
            return d / radio.base
        if not d.is_dir():
            return None
        skip = {self.extra_file(radio)}
        files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() == ext and f not in skip]
        return max(files, key=lambda f: f.name) if files else None

    def radio(self, rid: str) -> RadioDef:
        for r in self.radios:
            if r.id == rid:
                return r
        raise KeyError(f"no radio '{rid}' in radios.yaml (have: {', '.join(x.id for x in self.radios)})")


def read_radios_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_fleet(path: Path, paths: Optional["Paths"] = None, data: Optional[dict] = None) -> Fleet:
    """Load radios.yaml. Builds start from the latest (by name) file in radio-downloads/<radio id>/ unless `base:` pins one."""
    data = data if data is not None else read_radios_yaml(path)
    if paths is None:   # standard layout around this radios.yaml: <home>/config/radios.yaml
        from .paths import resolve
        cfg = Path(path).resolve().parent
        paths = resolve(home=str(cfg.parent), config=str(cfg), file_paths=data.get("paths"))
    radios = []
    for r in data["radios"]:
        kind = r["kind"]
        base = r.get("base")
        radios.append(RadioDef(
            id=r["id"], label=r.get("label", r["id"]), kind=kind, output=r.get("output", r["id"]),
            tiers=list(r.get("tiers", ["core"])), base=base, groups=r.get("groups"),
            remap=dict(r.get("remap", {})), capabilities=dict(r.get("capabilities", {})),
            extra=r.get("extra"), template_channel=r.get("template_channel"),
            settings=dict(r.get("settings") or {}),
        ))
    return Fleet(paths=paths, radios=radios, card_subtitle=str(data.get("card_subtitle", "")),
                 operator=dict(data.get("operator") or {}), theme=dict(data.get("theme") or {}))


def channels_for(plan: Plan, radio: RadioDef) -> list[tuple[int, Channel]]:
    """(location, channel) pairs this radio should get, before capability filtering."""
    out = []
    for g in plan.groups:
        if g.tier not in radio.tiers:
            continue
        if radio.groups is not None and g.id not in radio.groups:
            continue
        shift = 0
        if g.id in radio.remap and g.channels:
            shift = int(radio.remap[g.id]) - g.channels[0].ch
        for c in g.channels:
            out.append((c.ch + shift, c))
    return out
