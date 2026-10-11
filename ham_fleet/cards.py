"""Printable channel card + field guide (HTML, optional PDF via Playwright)."""
from __future__ import annotations

import html
from pathlib import Path

from .model import Channel, Plan

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
E = html.escape


def _tone(c: Channel) -> str:
    if c.tone_mode == "DTCS":
        return f"D{c.dcs:03d}"
    if c.tone_mode == "Tone":
        return f"{c.tone:.1f}"
    if c.tone_mode == "TSQL":
        return f"{c.tone:.1f}<sup>T</sup>"
    return ""


def _shift(c: Channel) -> str:
    if c.rx_only:
        return '<span class="rxo">RX</span>'
    if c.is_repeater:
        return f"{c.duplex}{c.offset:g}"
    return ""


def _note(c: Channel) -> str:
    return c.note.split(" (")[0].split(" - ")[0]


def _table(chs: list[Channel]) -> str:
    rows = "".join(
        f"<tr><td class=n>{c.ch}</td><td class=nm>{E(c.name)}<span class=n7>{E(c.short)}</span></td>"
        f"<td class=f>{c.freq:.4f}</td><td class=d>{_shift(c)}</td><td class=t>{_tone(c)}</td>"
        f"<td class=w>{E(_note(c))}</td></tr>" for c in chs)
    return ('<table class="ch"><thead><tr><th>Ch</th><th>Name</th><th>MHz</th><th>Shift</th><th>Tone</th>'
            f'<th>Where / note</th></tr></thead><tbody>{rows}</tbody></table>')


def _compact(chs: list[Channel]) -> str:
    items = "".join(f"<li><b>{c.ch}</b> {E(c.name)} <span class=f>{c.freq:.4f}</span></li>" for c in chs)
    return f'<ul class="compact">{items}</ul>'


def _air(chs: list[Channel], tdh3_start: int | None) -> str:
    head = "<th>Ch</th>" + ("<th>TD-H3</th>" if tdh3_start else "") + "<th>Name</th><th>MHz</th><th>What</th>"
    rows = ""
    for c in chs:
        td = f"<td class=n>{tdh3_start + c.ch - chs[0].ch}</td>" if tdh3_start else ""
        rows += (f"<tr><td class=n>{c.ch}</td>{td}<td class=nm>{E(c.name)}</td>"
                 f"<td class=f>{c.freq:.3f}</td><td class=w>{E(c.note)}</td></tr>")
    return f'<table class="ch air"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


def render(plan: Plan, tdh3_air_start: int | None = None, template: Path | None = None) -> str:
    tpl = (template or TEMPLATES / "field-cards.html").read_text(encoding="utf-8")
    core = ""
    air = ""
    for g in plan.groups:
        if not g.channels:
            continue
        if g.card in ("table", "compact"):
            body = _table(g.channels) if g.card == "table" else _compact(g.channels)
            rng = f"{g.channels[0].ch}–{g.channels[-1].ch}"
            core += f'<div class="blk"><h2>{E(g.title)} <small>Ch {rng}</small></h2><div class="scroll">{body}</div></div>'
        elif g.card == "air":
            air += _air(g.channels, tdh3_air_start)
    return tpl.replace("%%CORE%%", core).replace("%%AIR%%", air)


def write_cards(plan: Plan, outdir: Path, pdf: bool = False, tdh3_air_start: int | None = None,
                template: Path | None = None) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    body = render(plan, tdh3_air_start, template)
    page = outdir / "Fleet_Field_Cards.html"
    page.write_text('<!doctype html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
                    + body + "</body></html>", encoding="utf-8")
    files = [page]
    if pdf:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SystemExit("PDF needs Playwright:  pip install playwright && playwright install chromium")
        out = outdir / "Fleet_Field_Cards.pdf"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(page.resolve().as_uri())
            pg.wait_for_timeout(1200)
            pg.emulate_media(media="print")
            pg.pdf(path=str(out), format="Letter", print_background=True, prefer_css_page_size=True)
            b.close()
        files.append(out)
    return files


# ---------------------------------------------------------------- phone layout
def _fq(c: Channel) -> str:
    s = f"{c.freq:.4f}"
    return s[:-1] if s.endswith("0") else s


def _meta(c: Channel) -> str:
    parts = []
    if c.rx_only:
        parts.append('<span class="rxo">RX</span>')
    elif c.is_repeater:
        parts.append(f"{'+' if c.duplex == '+' else '−'}{c.offset:g}")
    if c.tone_mode == "Tone":
        parts.append(f"Tone {c.tone:.1f}")
    elif c.tone_mode == "TSQL":
        parts.append(f"TSQL {c.tone:.1f}")
    elif c.tone_mode == "DTCS":
        parts.append(f"DCS {c.dcs:03d}")
    if c.mode in ("AM", "NFM"):
        parts.append(c.mode)
    return " · ".join(parts)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in s.lower()).strip("-")


def _guide_from_desktop(tpl: str) -> str:
    """Turn the desktop template's <section id="guide"> blocks into collapsible <details>."""
    start = tpl.find('id="guide"')
    if start < 0:
        return ""
    cols = tpl.find('<div class="cols">', start)
    end = tpl.find("</section>", cols)
    if cols < 0 or end < 0:
        return ""
    body = tpl[cols + len('<div class="cols">'):end].rstrip()
    if body.endswith("</div>"):
        body = body[: -len("</div>")]           # closes .cols
    marker = '<div class="blk"><h2>'
    out = []
    for chunk in body.split(marker)[1:]:
        title, _, rest = chunk.partition("</h2>")
        rest = rest.rstrip()
        if rest.endswith("</div>"):
            rest = rest[: -len("</div>")]       # closes .blk
        title = title.split("<small>")[0].strip()
        out.append(f'<details><summary>{title}</summary><div class="gbody">{rest}</div></details>')
    if not out:
        return ""
    return '<section class="guide" id="guide"><h2>Field guide</h2>' + "".join(out) + "</section>"


def render_mobile(plan: Plan, subtitle: str = "", tdh3_air_start: int | None = None,
                  template: Path | None = None, desktop_template: Path | None = None) -> str:
    tpl = (template or TEMPLATES / "field-cards-mobile.html").read_text(encoding="utf-8")
    chips, secs = [], []
    for g in plan.groups:
        if not g.channels or g.card == "none":
            continue
        gid = "g-" + _slug(g.id)
        rng = f"{g.channels[0].ch}–{g.channels[-1].ch}"
        if g.card == "air" and tdh3_air_start:
            rng += f" (TD-H3 {tdh3_air_start}+)"
        rows = []
        for c in g.channels:
            q = " ".join([str(c.ch), c.name, c.short, c.note, _fq(c), g.title]).lower()
            note = _note(c)
            sub = f"<small>{E(note)}</small>" if note else ""
            rows.append(f'<li class="ch" data-q="{E(q)}"><span class="num">{c.ch}</span>'
                        f'<div class="mid"><b>{E(c.name)}</b>{sub}</div>'
                        f'<div class="rt"><span class="fq">{_fq(c)}</span><span class="meta">{_meta(c)}</span></div></li>')
        short = g.title.split(" (")[0]
        chips.append(f'<a href="#{gid}">{E(short)}</a>')
        secs.append(f'<section class="grp" id="{gid}"><h2>{E(g.title)} <small>{rng}</small></h2>'
                    f'<ul class="chs">{"".join(rows)}</ul></section>')
    guide = ""
    dt = desktop_template or TEMPLATES / "field-cards.html"
    if dt.exists():
        guide = _guide_from_desktop(dt.read_text(encoding="utf-8"))
        if guide:
            chips.append('<a href="#guide">Guide</a>')
    return (tpl.replace("%%SUBTITLE%%", E(subtitle or "Same numbers on every radio"))
               .replace("%%CHIPS%%", "".join(chips))
               .replace("%%CHANNELS%%", "".join(secs))
               .replace("%%GUIDE%%", guide))


def write_mobile(plan: Plan, outdir: Path, subtitle: str = "", tdh3_air_start: int | None = None,
                 template: Path | None = None, desktop_template: Path | None = None) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    body = render_mobile(plan, subtitle, tdh3_air_start, template, desktop_template)
    out = outdir / "Fleet_Field_Cards_Mobile.html"
    out.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                   "</head><body>" + body + "</body></html>", encoding="utf-8")
    return out
