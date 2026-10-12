"""Update a Baofeng DM32-UV NeonPlug export (.neonplug = zip with codeplug.json).

The tool "manages" the zones named by dm32_zone in channels.yaml. Their channels live as a
contiguous block at the end of the channel list. Each build:
  1. removes that managed tail and its zones,
  2. re-appends the current plan's channels and zones.
Everything else in the codeplug (DMR channels, contacts, other zones, settings) is untouched.

The NeonPlug format is unofficial, worked out from real exports, so always keep a backup
export of the radio and check the result in NeonPlug before writing it.
"""
from __future__ import annotations

import copy
import json
import random
import string
import time
import zipfile
from pathlib import Path

from .chirp_out import BuildResult
from .model import Plan, RadioDef, channels_for

NONE = {"type": "None"}


def _tone(v):
    return {"type": "CTCSS", "value": v}


def read_neonplug(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("codeplug.json"))


def write_neonplug(cp: dict, path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("codeplug.json", json.dumps(cp, separators=(",", ":")))


def _zone_id() -> str:
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"zone-{int(time.time() * 1000)}-{rnd}"


def build_neonplug(plan: Plan, radio: RadioDef, src: Path | None, outdir: Path, dry_run=False) -> BuildResult:
    """src = the NeonPlug export to start from (latest by name in radio-downloads/<radio id>/)."""
    res = BuildResult(radio.id)
    if src is None or not src.exists():
        raise SystemExit(f"{radio.id}: no NeonPlug export found (save one in radio-downloads/{radio.id}/; "
                         f"see `ham-fleet where`)")
    cp = read_neonplug(src)
    chans = cp["channels"]
    managed_names = {g.dm32_zone for g in plan.groups if g.dm32_zone}

    # 1. find and strip the managed tail
    managed_nums = {n for z in cp["zones"] if z["name"] in managed_names for n in z["channels"]}
    if managed_nums:
        first = min(managed_nums)
        tail = {c["number"] for c in chans if c["number"] >= first}
        if tail != managed_nums:
            stray = sorted(tail - managed_nums)[:5]
            raise SystemExit(
                f"{radio.id}: managed channels are not a clean block at the end "
                f"(unmanaged channels {stray} sit after channel {first}). "
                "Move them in NeonPlug, or remove the managed zones, then export again.")
        for z in cp["zones"]:
            if z["name"] not in managed_names and set(z["channels"]) & managed_nums:
                res.skipped.append(f"zone '{z['name']}' referenced managed channels; references removed")
                z["channels"] = [n for n in z["channels"] if n not in managed_nums]
        for s in cp.get("scanLists", []):
            if set(s.get("channels", [])) & managed_nums:
                res.skipped.append(f"scan list '{s['name']}' referenced managed channels; references removed")
                s["channels"] = [n for n in s["channels"] if n not in managed_nums]
        cp["channels"] = chans = [c for c in chans if c["number"] < first]
        cp["zones"] = [z for z in cp["zones"] if z["name"] not in managed_names]

    # 2. template for new analog channels
    tmpl = None
    for c in chans:
        if c.get("mode") == "Analog" and (not radio.template_channel or c["name"] == radio.template_channel):
            tmpl = c
            break
    if tmpl is None:
        raise SystemExit(f"{radio.id}: template channel '{radio.template_channel}' not found")

    nxt = max((c["number"] for c in chans), default=0) + 1
    zones: dict[str, list[int]] = {}
    for _, c in channels_for(plan, radio):
        grp = plan.group(c.group)
        if not grp.dm32_zone:
            continue
        if c.mode == "AM":
            res.skipped.append(f"ch {c.ch} {c.name}: DM32 has no air band")
            continue
        if c.tone_mode == "DTCS":
            res.skipped.append(f"ch {c.ch} {c.name}: DCS not supported by this writer yet")
            continue
        n = copy.deepcopy(tmpl)
        n.update(
            number=nxt, name=c.name[:16], rxFrequency=c.freq,
            txFrequency=c.freq if c.rx_only else c.tx_freq,
            bandwidth="12.5kHz" if c.mode == "NFM" else "25kHz",
            power=c.power, forbidTx=c.rx_only, scanAdd=False, scanListId=0,
            txCtcssDcs=_tone(c.tone) if c.tone_mode in ("Tone", "TSQL") else NONE,
            rxCtcssDcs=_tone(c.tone) if c.tone_mode == "TSQL" else NONE,
        )
        chans.append(n)
        zones.setdefault(grp.dm32_zone, []).append(nxt)
        nxt += 1
    for name, lst in zones.items():
        cp["zones"].append({"id": _zone_id(), "name": name, "channels": lst})
    cp["exportDate"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    res.written = sum(len(v) for v in zones.values())
    if not dry_run:
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{radio.output}.neonplug"
        write_neonplug(cp, out)
        res.files.append(out)
    return res
