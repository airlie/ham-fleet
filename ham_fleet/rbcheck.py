"""Compare plan repeaters against RepeaterBook exports. Reports only; never edits the plan.

Accepts both RepeaterBook CSV flavours:
  - "CHIRP" export  (Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,...)
  - plain export    (Output Freq,Input Freq,Offset,Uplink Tone,Downlink Tone,Call,...)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .model import Plan


@dataclass
class RBEntry:
    freq: float
    duplex: str
    offset: float
    tone: str      # "" | "123.0" | "D315"
    label: str


def _f(x):
    try:
        return float(str(x).strip())
    except ValueError:
        return None


def load_rb(paths: list[Path]) -> list[RBEntry]:
    out = []
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            for row in rd:
                if "Frequency" in row:          # CHIRP flavour
                    f = _f(row.get("Frequency"))
                    if f is None:
                        continue
                    tm = (row.get("Tone") or "").strip()
                    if tm == "Tone":
                        tone = f"{float(row['rToneFreq']):.1f}"
                    elif tm == "TSQL":
                        # RB/CHIRP store the TSQL tone in cToneFreq
                        tone = f"{float(row.get('cToneFreq') or row['rToneFreq']):.1f}"
                    elif tm == "DTCS":
                        tone = f"D{int(row['DtcsCode']):03d}"
                    else:
                        tone = ""
                    out.append(RBEntry(f, (row.get("Duplex") or "").strip(), _f(row.get("Offset")) or 0.0,
                                       tone, f"{row.get('Name','').strip()} {row.get('Comment','').strip()}".strip()))
                elif "Output Freq" in row:      # plain flavour
                    f = _f(row["Output Freq"])
                    if f is None:
                        continue
                    up = (row.get("Uplink Tone") or "").strip()
                    tone = up if up.startswith("D") else (f"{float(up):.1f}" if _f(up) else "")
                    inp = _f(row.get("Input Freq")) or f
                    out.append(RBEntry(f, "+" if inp > f else "-" if inp < f else "", round(abs(inp - f), 4),
                                       tone, f"{row.get('Call','')} {row.get('Location','')}".strip()))
    return out


def check(plan: Plan, entries: list[RBEntry]) -> list[str]:
    lines = []
    by_f: dict[float, list[RBEntry]] = {}
    for e in entries:
        by_f.setdefault(round(e.freq, 4), []).append(e)
    for c in plan.channels:
        if not c.is_repeater or c.rx_only or 462.0 < c.freq < 468.0:
            continue
        mine = (f"D{c.dcs:03d}" if c.tone_mode == "DTCS"
                else f"{c.tone:.1f}" if c.tone_mode in ("Tone", "TSQL") else "")
        cands = by_f.get(round(c.freq, 4), [])
        if not cands:
            lines.append(f"NOT FOUND  ch {c.ch:>4} {c.name:<13} {c.freq:.4f}  not in these RepeaterBook files")
            continue
        exact = [e for e in cands if e.duplex == c.duplex and e.tone == mine]
        if exact:
            continue
        alt = "; ".join(f"{e.duplex}{e.offset:g} tone {e.tone or 'none'} ({e.label[:40]})" for e in cands[:3])
        lines.append(f"DIFFERENT  ch {c.ch:>4} {c.name:<13} {c.freq:.4f} plan {c.duplex}{c.offset:g} tone "
                     f"{mine or 'none'}  | RepeaterBook: {alt}")
    return lines
