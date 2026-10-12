"""Build CHIRP images and CSVs using CHIRP's own radio drivers.

CHIRP isn't published on PyPI, so we load it from a source checkout:
  1. an importable `chirp` package, if already installed
  2. $HAM_FLEET_CHIRP (or the older $FLEET_CHIRP_PATH)
  3. ./vendor/chirp next to this project
"""
from __future__ import annotations

import csv
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from .model import Channel, RadioDef, channels_for, Plan

_CHIRP = None


def chirp():
    """Import CHIRP lazily and return (directory, chirp_common, generic_csv)."""
    global _CHIRP
    if _CHIRP:
        return _CHIRP
    try:
        import chirp  # noqa: F401
    except ImportError:
        candidates = [os.environ.get("HAM_FLEET_CHIRP"), os.environ.get("FLEET_CHIRP_PATH"),
                      str(Path(__file__).resolve().parent.parent / "vendor" / "chirp")]
        for p in candidates:
            if p and (Path(p) / "chirp" / "__init__.py").exists():
                sys.path.insert(0, p)
                break
        else:
            raise SystemExit(
                "CHIRP source not found. Run:\n"
                "  git clone --depth 1 https://github.com/kk7ds/chirp.git vendor/chirp\n"
                "or set HAM_FLEET_CHIRP to a CHIRP checkout.")
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from chirp import chirp_common, directory
    from chirp.drivers import generic_csv
    directory.import_drivers()
    _CHIRP = (directory, chirp_common, generic_csv)
    return _CHIRP


@dataclass
class BuildResult:
    radio: str
    written: int = 0
    skipped: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    settings_changed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = f"{self.radio}: {self.written} channels"
        if self.skipped:
            s += f", {len(self.skipped)} skipped"
        return s


class _Features:
    """Stand-in radio features for chirp-csv radios (no image to read them from)."""

    def __init__(self, caps: dict):
        _, cc, _ = chirp()
        self.memory_bounds = tuple(caps.get("bounds", (1, 999)))
        self.valid_modes = list(caps.get("modes", ["FM", "NFM"]))
        self.valid_bands = [(int(a * 1e6), int(b * 1e6)) for a, b in caps.get("bands", [[136, 174], [400, 520]])]
        self.valid_duplexes = ["", "+", "-", "split", "off"]
        self.valid_name_length = int(caps.get("name_length", 12))
        self.valid_power_levels = [cc.PowerLevel(k, watts=float(v))
                                   for k, v in caps.get("power", {"Low": 1, "High": 5}).items()]


def _fits(feat, loc: int, c: Channel) -> str | None:
    lo, hi = feat.memory_bounds
    if not lo <= loc <= hi:
        return f"location {loc} outside {lo}-{hi}"
    if c.mode not in feat.valid_modes:
        return f"mode {c.mode} not supported"
    f = int(round(c.freq * 1e6))
    if not any(a <= f <= b for a, b in feat.valid_bands):
        return f"{c.freq} MHz outside radio bands"
    return None


def to_memory(feat, loc: int, c: Channel):
    _, cc, _ = chirp()
    m = cc.Memory()
    m.number = loc
    m.freq = int(round(c.freq * 1e6))
    m.name = c.name if feat.valid_name_length >= 12 else c.short
    if c.rx_only:
        m.duplex, m.offset = "off", 0
    else:
        m.duplex = c.duplex
        m.offset = int(round(c.offset * 1e6))
    m.tmode = c.tone_mode
    if c.tone_mode in ("Tone", "TSQL"):
        m.rtone = m.ctone = c.tone
    if c.tone_mode == "DTCS":
        m.dtcs = m.rx_dtcs = c.dcs
    m.mode = c.mode
    m.skip = "S" if c.scan_skip else ""
    levels = sorted(feat.valid_power_levels or [], key=float)
    if levels:
        m.power = levels[-1] if c.power == "High" else levels[0]
    m.comment = (c.group_title + (" | " + c.note if c.note else ""))[:60]
    return m


def _write_csv(feat, mems, path: Path) -> None:
    _, _, generic_csv = chirp()
    r = generic_csv.CSVRadio(None)
    for m in mems:
        r.set_memory(m)
    r.save(str(path))
    # CSVRadio keeps a default row 0; drop it unless we actually wrote location 0
    used = {m.number for m in mems}
    if 0 not in used:
        rows = list(csv.reader(path.open(newline="")))
        rows = [rows[0]] + [x for x in rows[1:] if x and x[0] != "0"]
        with path.open("w", newline="") as fh:
            csv.writer(fh).writerows(rows)


def build_chirp(plan: Plan, radio: RadioDef, src: Path | None, outdir: Path, dry_run=False,
                extra_src: Path | None = None) -> BuildResult:
    """src = the radio download to start from (chirp-image); extra_src = image for `extra:`."""
    directory, cc, _ = chirp()
    warnings.simplefilter("ignore", DeprecationWarning)  # CHIRP's older drivers are noisy
    res = BuildResult(radio.id)
    if radio.kind == "chirp-image":
        if src is None or not src.exists():
            raise SystemExit(f"{radio.id}: no radio download found (save one in radio-downloads/{radio.id}/; "
                             f"see `ham-fleet where`)")
        r = directory.get_radio_by_image(str(src))
        feat = r.get_features()
    else:
        r = None
        feat = _Features(radio.capabilities)

    mems = []
    for loc, c in channels_for(plan, radio):
        why = _fits(feat, loc, c)
        if why:
            res.skipped.append(f"ch {c.ch} {c.name}: {why}")
            continue
        m = to_memory(feat, loc, c)
        if r is not None:
            errs = [str(e) for e in r.validate_memory(m) if isinstance(e, cc.ValidationError)]
            if errs:
                res.skipped.append(f"ch {c.ch} {c.name}: {'; '.join(errs)}")
                continue
        mems.append(m)

    if radio.extra and r is not None:
        ex = radio.extra
        if extra_src is None or not extra_src.exists():
            raise SystemExit(f"{radio.id}: extra image not found: {extra_src}")
        srcx = directory.get_radio_by_image(str(extra_src))
        lo, hi = srcx.get_features().memory_bounds
        nxt = int(ex["start"])
        top = feat.memory_bounds[1]
        for i in range(lo, hi + 1):
            m = srcx.get_memory(i)
            if m.empty or (ex.get("named_only") and not m.name.strip()):
                continue
            if nxt > top:
                res.skipped.append(f"extra memory '{m.name}': no room above {top}")
                continue
            m = m.dupe()
            m.number = nxt
            if ex.get("scan_skip"):
                m.skip = "S"
            mems.append(m)
            nxt += 1

    res.written = len(mems)
    if radio.settings and r is None:
        res.skipped.append("settings: ignored for chirp-csv radios (CSV files carry no settings)")
    if dry_run:
        return res
    outdir.mkdir(parents=True, exist_ok=True)
    if r is not None:
        lo, hi = feat.memory_bounds
        for i in range(lo, hi + 1):
            if not r.get_memory(i).empty:
                r.erase_memory(i)
        for m in mems:
            r.set_memory(m)
        if radio.settings:
            from .radio_settings import apply_settings
            try:
                res.settings_changed = apply_settings(r, radio.settings)
            except ValueError as e:
                raise SystemExit(f"{radio.id}: {e}")
        img = outdir / f"{radio.output}.img"
        r.save_mmap(str(img))
        # read back to make sure the image is valid
        check = directory.get_radio_by_image(str(img))
        n = sum(1 for i in range(lo, hi + 1) if not check.get_memory(i).empty)
        if n != len(mems):
            raise SystemExit(f"{radio.id}: wrote {len(mems)} but image reads back {n}")
        res.files.append(img)
    csvp = outdir / f"{radio.output}.csv"
    _write_csv(feat, mems, csvp)
    res.files.append(csvp)
    return res
