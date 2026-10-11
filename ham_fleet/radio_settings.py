"""Apply and list radio settings (voice prompts, beep, timers...) on CHIRP images.

Uploading a CHIRP image writes the radio's settings as well as its channels, so settings changed
on the radio after its backup was taken get reverted. Settings listed in radios.yaml are applied
on every build. Use the normalized names from settings_catalog.py (voice_prompt, key_beep, ...);
anything else is treated as a raw CHIRP setting name.
"""
from __future__ import annotations

from typing import Iterator

from .settings_catalog import BY_NAME, SettingError, current, resolve, supported


def _walk(group) -> Iterator:
    from chirp import settings as cs
    for el in group:
        if isinstance(el, cs.RadioSetting):
            yield el
        elif isinstance(el, cs.RadioSettingGroup):
            yield from _walk(el)


def describe(value) -> tuple[str, str]:
    """(current value, allowed values) as text."""
    from chirp import settings as cs
    if isinstance(value, cs.RadioSettingValueList):
        return str(value.get_value()), " | ".join(value.get_options())
    if isinstance(value, cs.RadioSettingValueBoolean):
        return str(bool(value.get_value())).lower(), "true | false"
    if isinstance(value, (cs.RadioSettingValueInteger, cs.RadioSettingValueFloat)):
        return str(value.get_value()), f"{value.get_min()}..{value.get_max()}"
    if isinstance(value, cs.RadioSettingValueString):
        return repr(value.get_value()), "text"
    return str(value), "?"


def _by_name(root) -> dict:
    return {el.get_name(): el for el in _walk(root)}


def list_settings(radio, contains: str = "") -> list[tuple[str, str, str, str]]:
    """Raw CHIRP view: (name, label, current, allowed) for every setting the driver exposes."""
    out = []
    for el in _walk(radio.get_settings()):
        if contains and contains.lower() not in (el.get_name() + el.get_shortname()).lower():
            continue
        try:
            cur, allowed = describe(el.value)
        except Exception:  # some drivers expose odd composite values
            cur, allowed = "?", "?"
        out.append((el.get_name(), el.get_shortname(), cur, allowed))
    return out


def list_normalized(radio) -> list[tuple[str, str, str, str, str]]:
    """Normalized view: (name, allowed values, current value, CHIRP names it maps to, help)."""
    names = _by_name(radio.get_settings())
    out = []
    for entry, targets in supported(names):
        cur = current(entry, names)
        out.append((entry.name, entry.values, cur if cur is not None else "-",
                    ", ".join(targets) if targets else "not on this radio", entry.help))
    return out


def _coerce_raw(el, want):
    from chirp import settings as cs
    v = el.value
    name = el.get_name()
    if isinstance(v, cs.RadioSettingValueList):
        opts = v.get_options()
        for o in opts:
            if str(o).lower() == str(want).lower():
                return o
        raise SettingError(f"setting '{name}': '{want}' is not one of {opts}")
    if isinstance(v, cs.RadioSettingValueBoolean):
        if isinstance(want, bool):
            return want
        s = str(want).lower()
        if s in ("true", "on", "yes", "1"):
            return True
        if s in ("false", "off", "no", "0"):
            return False
        raise SettingError(f"setting '{name}': '{want}' is not true/false")
    if isinstance(v, cs.RadioSettingValueInteger):
        return int(want)
    if isinstance(v, cs.RadioSettingValueFloat):
        return float(want)
    return str(want)


def plan_settings(radio, wanted: dict) -> list[tuple[str, str, object]]:
    """Translate radios.yaml settings into [(label, chirp name, chirp value)] without changing anything."""
    names = _by_name(radio.get_settings())
    out = []
    # language before voice_prompt so "voice_prompt: off" wins on radios that share one setting
    order = sorted(wanted, key=lambda k: 0 if k == "voice_language" else 1)
    for key in order:
        want = wanted[key]
        if key in BY_NAME:
            for chirp_name, val in resolve(key, want, names):
                out.append((key, chirp_name, val))
        elif key in names:
            out.append((key, key, _coerce_raw(names[key], want)))
        else:
            raise SettingError(f"unknown setting '{key}' for {radio.MODEL}: not a ham-fleet setting "
                               f"({', '.join(BY_NAME)}) and not a CHIRP name on this radio")
    return out


def apply_settings(radio, wanted: dict) -> list[str]:
    """Set the requested settings on a loaded CHIRP radio. Returns a change log."""
    if not wanted:
        return []
    steps = plan_settings(radio, wanted)
    root = radio.get_settings()
    names = _by_name(root)
    log = []
    for label, chirp_name, val in steps:
        el = names[chirp_name]
        old, _ = describe(el.value)
        el.value.set_value(val)
        el.value._has_changed = True  # make sure set_settings writes it
        now, _ = describe(el.value)
        if old != now:
            via = "" if label == chirp_name else f" ({chirp_name})"
            log.append(f"{label}{via}: {old} -> {now}")
    radio.set_settings(root)
    return log
