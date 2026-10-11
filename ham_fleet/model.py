"""Channel plan and fleet config: loading and data classes."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

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


@dataclass
class Fleet:
    backups_dir: Path
    output_dir: Path
    radios: list[RadioDef]
    card_subtitle: str = ""

    def radio(self, rid: str) -> RadioDef:
        for r in self.radios:
            if r.id == rid:
                return r
        raise KeyError(f"no radio '{rid}' in radios.yaml (have: {', '.join(x.id for x in self.radios)})")


def load_fleet(path: Path, backups: Optional[str] = None, output: Optional[str] = None) -> Fleet:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    base = path.parent
    bdir = backups or os.environ.get("FLEET_BACKUPS") or data.get("backups_dir", ".")
    odir = output or data.get("output_dir", "out")
    bpath = Path(bdir)
    opath = Path(odir)
    radios = []
    for r in data["radios"]:
        radios.append(RadioDef(
            id=r["id"], label=r.get("label", r["id"]), kind=r["kind"], output=r["output"],
            tiers=list(r.get("tiers", ["core"])), base=r.get("base"), groups=r.get("groups"),
            remap=dict(r.get("remap", {})), capabilities=dict(r.get("capabilities", {})),
            extra=r.get("extra"), template_channel=r.get("template_channel"),
            settings=dict(r.get("settings") or {}),
        ))
    return Fleet(backups_dir=bpath if bpath.is_absolute() else (base / bpath).resolve(),
                 output_dir=opath if opath.is_absolute() else (base / opath).resolve(),
                 radios=radios, card_subtitle=str(data.get("card_subtitle", "")))


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
