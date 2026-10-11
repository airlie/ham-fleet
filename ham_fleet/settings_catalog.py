"""Normalized radio settings.

Users write one vocabulary in radios.yaml:

    settings:
      voice_prompt: off
      key_beep: off
      tx_timeout: 60        # seconds, 0 = off
      display: name

and each catalog entry knows the CHIRP setting names and value formats different drivers use.
When a driver has none of an entry's targets, the build stops and says so. Any key that isn't
in the catalog is passed straight through as a raw CHIRP setting name (escape hatch for quirks).

To support a new radio, run `ham-fleet settings RADIO --raw`, then add its CHIRP names to the
`targets` of the matching entries below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

OFF_WORDS = {"off", "false", "no", "0", "disable", "disabled", "none"}
ON_WORDS = {"on", "true", "yes", "1", "enable", "enabled"}


class SettingError(ValueError):
    pass


def to_bool(v: Any, name: str) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ON_WORDS:
        return True
    if s in OFF_WORDS:
        return False
    raise SettingError(f"{name}: expected on/off, got '{v}'")


def _is_off_option(o: str) -> bool:
    return str(o).strip().lower() in OFF_WORDS


def _first_number(s: str):
    m = re.search(r"\d+(\.\d+)?", str(s))
    return float(m.group()) if m else None


# --------------------------------------------------------------------------- value translators
# Each takes (wanted value, CHIRP setting element, entry name, extra) and returns the CHIRP value.

def t_bool(want, el, name, extra):
    return to_bool(want, name)


def t_bool_inverted(want, el, name, extra):
    return not to_bool(want, name)


def t_onoff_list(want, el, name, extra):
    opts = el.value.get_options()
    if to_bool(want, name):
        for pref in extra.get("on", ["On"]):
            if pref in opts:
                return pref
        return next(o for o in opts if not _is_off_option(o))
    for o in opts:
        if _is_off_option(o):
            return o
    raise SettingError(f"{name}: this radio has no off value ({opts})")


def t_voice_list(want, el, name, extra):
    """UV-5R style: one list holding Off plus the languages."""
    opts = el.value.get_options()
    if to_bool(want, name):
        cur = el.value.get_value()
        return cur if not _is_off_option(cur) else next(o for o in opts if not _is_off_option(o))
    return next(o for o in opts if _is_off_option(o))


def t_choice(want, el, name, extra):
    """Match a word against the options (case-insensitive, prefix allowed), via an optional alias map."""
    opts = el.value.get_options()
    w = str(want).strip().lower()
    w = extra.get("aliases", {}).get(w, w)
    for o in opts:
        if o.lower() == w:
            return o
    for o in opts:
        if o.lower().startswith(w):
            return o
    raise SettingError(f"{name}: '{want}' is not available on this radio (options: {', '.join(opts)})")


def t_seconds(want, el, name, extra):
    """Timers: number of seconds, 0/off = off, 'always' where a radio has an always-on option."""
    from chirp import settings as cs
    v = el.value
    s = str(want).strip().lower()
    if isinstance(v, cs.RadioSettingValueInteger):
        n = 0 if s in OFF_WORDS else int(float(s))
        if not v.get_min() <= n <= v.get_max():
            raise SettingError(f"{name}: {n} outside {v.get_min()}..{v.get_max()} on this radio")
        return n
    opts = v.get_options()
    if s in ("always", "always on"):
        for o in opts:
            if o.lower().startswith("always"):
                return o
        raise SettingError(f"{name}: this radio has no always-on option ({', '.join(opts)})")
    if s in OFF_WORDS:
        for o in opts:
            if _is_off_option(o):
                return o
        raise SettingError(f"{name}: this radio can't turn this off ({', '.join(opts)})")
    n = float(s)
    for o in opts:
        if _first_number(o) == n:
            return o
    raise SettingError(f"{name}: {s} seconds is not available on this radio (options: {', '.join(opts)})")


def t_level(want, el, name, extra):
    """Plain levels (squelch 0-9, VOX 1-10). 0/off maps to an Off option when the radio has one."""
    from chirp import settings as cs
    v = el.value
    s = str(want).strip().lower()
    if isinstance(v, cs.RadioSettingValueInteger):
        n = 0 if s in OFF_WORDS else int(s)
        if not v.get_min() <= n <= v.get_max():
            raise SettingError(f"{name}: {n} outside {v.get_min()}..{v.get_max()} on this radio")
        return n
    opts = v.get_options()
    if s in OFF_WORDS:
        for o in opts:
            if _is_off_option(o):
                return o
    for o in opts:
        if o.strip().lower() == s:
            return o
    raise SettingError(f"{name}: '{want}' is not available on this radio (options: {', '.join(opts)})")


# --------------------------------------------------------------------------- catalog
@dataclass
class Target:
    chirp: str                       # CHIRP setting name
    fn: Callable                     # translator
    extra: dict = field(default_factory=dict)


@dataclass
class Entry:
    name: str
    help: str
    values: str
    targets: list[Target]
    all_targets: bool = False        # set every target present (A/B display), not just the first


CATALOG: list[Entry] = [
    Entry("voice_prompt", "Spoken voice prompts", "on | off", [
        Target("settings.voicesw", t_bool),            # K5 family: UV-5R Mini, UV-32, UV-25/26
        Target("voice", t_voice_list),                  # UV-5R family
    ]),
    Entry("voice_language", "Language for voice prompts", "english | chinese", [
        Target("settings.voice", t_choice),
        Target("voice", t_choice),
    ]),
    Entry("key_beep", "Key press beep", "on | off", [
        Target("beep", t_bool),
        Target("settings.beep", t_onoff_list, {"on": ["On", "Beep"]}),
    ]),
    Entry("roger_beep", "Roger beep at end of transmission", "on | off", [
        Target("roger", t_bool),
        Target("settings.roger", t_bool),
    ]),
    Entry("dual_watch", "Dual watch / dual standby", "on | off", [
        Target("tdr", t_bool),
        Target("settings.dualstandby", t_onoff_list),
    ]),
    Entry("tx_timeout", "Transmit time-out timer", "seconds (e.g. 60), or off", [
        Target("timeout", t_seconds),
        Target("settings.tot", t_seconds),
    ]),
    Entry("squelch", "Squelch level (scale differs: UV-5R 0-9, K5 family off/1-5)", "number, or off", [
        Target("squelch", t_level),
        Target("settings.squelch", t_level),
    ]),
    Entry("backlight", "Backlight time-out", "seconds, or always", [
        Target("abr", t_seconds),
        Target("settings.backlight", t_seconds),
    ]),
    Entry("battery_save", "Battery saver", "on | off", [
        Target("save", t_onoff_list, {"on": ["1:3", "1:2", "1:1", "1:4"]}),
        Target("settings.savemode", t_onoff_list),
    ]),
    Entry("auto_key_lock", "Lock the keypad automatically", "on | off", [
        Target("autolk", t_bool),
        Target("settings.autolock", t_bool),
    ]),
    Entry("fm_radio", "Broadcast FM radio function", "on | off", [
        Target("fmradio", t_bool),
        Target("settings.fmenable", t_bool_inverted),   # K5 driver calls it "Disable FM radio"
    ]),
    Entry("squelch_tail_elim", "Squelch tail elimination (radio to radio)", "on | off", [
        Target("ste", t_bool),
        Target("settings.tailclear", t_bool),
    ]),
    Entry("display", "What the channel display shows", "name | frequency | channel", [
        Target("mdfa", t_choice), Target("mdfb", t_choice),
        Target("settings.chadistype", t_choice), Target("settings.chbdistype", t_choice),
    ], all_targets=True),
    Entry("scan_resume", "When scanning resumes", "time | carrier | search", [
        Target("screv", t_choice, {"aliases": {"time": "to", "carrier": "co", "search": "se"}}),
        Target("settings.scanmode", t_choice),
    ]),
    Entry("vox", "VOX (voice-operated transmit)", "off, or a level (1-9)", []),  # handled by _vox()
]
BY_NAME = {e.name: e for e in CATALOG}


def _vox(want, by_name) -> list[tuple[str, Any]]:
    s = str(want).strip().lower()
    off = s in OFF_WORDS
    out = []
    if "settings.voxsw" in by_name:                       # Mini / UV-32: switch + level
        out.append(("settings.voxsw", not off))
        if not off:
            out.append(("settings.vox", t_level(s, by_name["settings.vox"], "vox", {})))
    elif "settings.vox" in by_name:                       # UV-25/26: level list with Off
        out.append(("settings.vox", t_level(s, by_name["settings.vox"], "vox", {})))
    elif "vox" in by_name:                                # UV-5R: OFF | 1..10
        out.append(("vox", t_level(s, by_name["vox"], "vox", {})))
    else:
        raise SettingError("vox: this radio has no VOX setting")
    return out


def resolve(name: str, want: Any, by_name: dict) -> list[tuple[str, Any]]:
    """Normalized name + value -> [(chirp name, chirp value), ...] for this radio's settings."""
    if name == "vox":
        return _vox(want, by_name)
    entry = BY_NAME[name]
    present = [t for t in entry.targets if t.chirp in by_name]
    if not present:
        raise SettingError(f"{name}: no equivalent setting on this radio. Use a raw CHIRP name instead "
                           f"(see `ham-fleet settings <radio> --raw`)")
    if not entry.all_targets:
        present = present[:1]
    return [(t.chirp, t.fn(want, by_name[t.chirp], name, t.extra)) for t in present]


def supported(by_name: dict) -> list[tuple[Entry, list[str]]]:
    """Catalog entries and the CHIRP names they map to on this radio."""
    out = []
    for e in CATALOG:
        if e.name == "vox":
            names = [n for n in ("settings.voxsw", "settings.vox", "vox") if n in by_name]
        else:
            names = [t.chirp for t in e.targets if t.chirp in by_name]
            if names and not e.all_targets:
                names = names[:1]
        out.append((e, names))
    return out


# --------------------------------------------------------------------------- reading values back
def _raw(el):
    return el.value.get_value()


def _normal_value(t: Target, el) -> str:
    v = _raw(el)
    fn = t.fn
    if fn is t_bool:
        return "on" if v else "off"
    if fn is t_bool_inverted:
        return "off" if v else "on"
    if fn in (t_onoff_list, t_voice_list):
        return "off" if _is_off_option(v) else "on"
    if fn is t_seconds:
        if isinstance(v, (int, float)):
            return str(v)
        if _is_off_option(v):
            return "off"
        if str(v).lower().startswith("always"):
            return "always"
        n = _first_number(v)
        return str(int(n)) if n is not None else str(v)
    if fn is t_level:
        return "off" if _is_off_option(v) else str(v)
    if fn is t_choice:
        rev = {b: a for a, b in t.extra.get("aliases", {}).items()}
        s = str(v).lower()
        return rev.get(s, s.split()[0] if s else s)
    return str(v)


def current(entry: Entry, by_name: dict) -> str | None:
    """This radio's current value in ham-fleet terms, or None if unsupported."""
    if entry.name == "vox":
        if "settings.voxsw" in by_name:
            return str(_raw(by_name["settings.vox"])) if _raw(by_name["settings.voxsw"]) else "off"
        for n in ("settings.vox", "vox"):
            if n in by_name:
                v = _raw(by_name[n])
                return "off" if _is_off_option(v) else str(v)
        return None
    present = [t for t in entry.targets if t.chirp in by_name]
    if not present:
        return None
    vals = {_normal_value(t, by_name[t.chirp]) for t in (present if entry.all_targets else present[:1])}
    return " / ".join(sorted(vals))
