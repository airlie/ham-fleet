"""Sanity checks on the channel plan. Errors stop a build; warnings are reported."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .model import MODES, POWERS, TONE_MODES, Plan

AIRBAND = (108.0, 137.0)
NOAA = (162.390, 162.560)
MARINE = (156.0, 162.1)
AAR = (159.81, 161.58)
FRS_GMRS = (462.55, 467.725)
CTCSS = {67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2,
         110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2,
         165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
         206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1}
HAM = [(50.0, 54.0), (144.0, 148.0), (222.0, 225.0), (420.0, 450.0)]


@dataclass
class Issue:
    level: str   # "error" | "warn"
    ch: int
    name: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} ch {self.ch:>4} {self.name:<13} {self.msg}"


def _in(f, rng):
    return rng[0] <= f <= rng[1]


def validate_plan(plan: Plan) -> list[Issue]:
    issues: list[Issue] = []
    seen = defaultdict(list)
    for c in plan.channels:
        E = lambda m: issues.append(Issue("error", c.ch, c.name, m))
        W = lambda m: issues.append(Issue("warn", c.ch, c.name, m))
        seen[c.ch].append(c)
        if len(c.name) > 12:
            E(f"name longer than 12 chars ({len(c.name)})")
        if len(c.short) > 7:
            E(f"short name longer than 7 chars ({len(c.short)})")
        if c.mode not in MODES:
            E(f"mode '{c.mode}' not one of {MODES}")
        if c.power not in POWERS:
            E(f"power '{c.power}' not one of {POWERS}")
        if c.tone_mode not in TONE_MODES:
            E(f"tone_mode '{c.tone_mode}' not one of {TONE_MODES}")
        if c.tone_mode in ("Tone", "TSQL") and c.tone not in CTCSS:
            E(f"tone {c.tone} is not a standard CTCSS tone")
        if c.duplex not in ("", "+", "-"):
            E(f"duplex '{c.duplex}' must be +, - or empty")
        if c.is_repeater and c.offset <= 0:
            E("repeater channel without an offset")
        # band-specific rules
        if _in(c.freq, AIRBAND):
            if c.mode != "AM":
                E("air band must be AM")
            if not c.rx_only:
                E("air band must be rx_only")
        elif c.mode == "AM":
            E("AM outside the air band")
        for rng, what in ((NOAA, "NOAA weather"), (AAR, "railroad"), (MARINE, "marine")):
            if _in(c.freq, rng) and not c.rx_only and not any(_in(c.freq, h) for h in HAM):
                E(f"{what} frequency must be rx_only")
        if c.is_repeater:
            if _in(c.freq, (144.0, 148.0)):
                if abs(c.offset - 0.6) > 1e-6:
                    W(f"2 m offset {c.offset} (usually 0.6)")
                if 146.61 <= c.freq <= 146.97 and c.duplex == "+":
                    W("146.61-146.97 usually uses - offset (check RepeaterBook)")
                if 147.0 <= c.freq <= 147.39 and c.duplex == "-":
                    W("147.00-147.39 usually uses + offset (check RepeaterBook)")
            if _in(c.freq, (420.0, 450.0)) and abs(c.offset - 5.0) > 1e-6:
                W(f"70 cm offset {c.offset} (usually 5.0)")
            if not any(_in(c.tx_freq, h) for h in HAM) and not _in(c.freq, FRS_GMRS):
                E(f"transmit frequency {c.tx_freq} is outside the ham bands")
        if c.is_repeater and not c.tone_mode:
            W("repeater with no tone (fine if the repeater is carrier access)")
    for ch, lst in seen.items():
        if len(lst) > 1:
            names = ", ".join(x.name for x in lst)
            issues.append(Issue("error", ch, lst[0].name, f"channel number used more than once: {names}"))
    return issues
