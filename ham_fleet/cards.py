"""Printable channel card + field guide (HTML, optional PDF via Playwright)."""
from __future__ import annotations

import html
import re
from pathlib import Path

from .model import Channel, Plan

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
E = html.escape

# ---------------------------------------------------------------- theme (accent color)
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _hex(value: str, key: str) -> str:
    m = _HEX.match(str(value).strip())
    if not m:
        raise SystemExit(f"theme.{key}: '{value}' is not a #RRGGBB color")
    return "#" + m.group(1).upper()


def _mix(hexc: str, other: str, t: float) -> str:
    a = [int(hexc[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def theme_css(theme: dict | None) -> str:
    """CSS that overrides --accent in every printable. theme: {accent, accent_dark?}.

    accent       used on light backgrounds and in print
    accent_dark  used in dark mode on screen (default: the accent lightened so it stays readable)
    """
    if not theme or not theme.get("accent"):
        return ""
    acc = _hex(theme["accent"], "accent")
    dark = _hex(theme["accent_dark"], "accent_dark") if theme.get("accent_dark") else _mix(acc, "#FFFFFF", 0.38)
    return ('<style id="ham-fleet-theme">'
            f':root{{--accent:{acc}}}'
            f'@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--accent:{dark}}}}}'
            f':root[data-theme="dark"]{{--accent:{dark}}}'
            f'@media print{{:root{{--accent:{acc}}}}}'
            '</style>')


def themed(page: str, theme: dict | None) -> str:
    css = theme_css(theme)
    if not css:
        return page
    return page.replace("</body>", css + "</body>", 1) if "</body>" in page else page + css


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
                template: Path | None = None, theme: dict | None = None) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    body = render(plan, tdh3_air_start, template)
    page = outdir / "Fleet_Field_Cards.html"
    page.write_text(themed('<!doctype html><html><head><meta charset="utf-8">'
                           '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
                           + body + "</body></html>", theme), encoding="utf-8")
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
                 template: Path | None = None, desktop_template: Path | None = None,
                 theme: dict | None = None) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    body = render_mobile(plan, subtitle, tdh3_air_start, template, desktop_template)
    out = outdir / "Fleet_Field_Cards_Mobile.html"
    out.write_text(themed('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                          '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                          "</head><body>" + body + "</body></html>", theme), encoding="utf-8")
    return out


# ---------------------------------------------------------------- QSO log + QSL cards
def _op(operator: dict) -> dict:
    o = {k: str(v) for k, v in (operator or {}).items() if v is not None}
    o.setdefault("callsign", "N0CALL")
    o["callsign"] = o["callsign"].upper()
    for k in ("name", "qth", "grid", "county", "dmr_id", "email"):
        o.setdefault(k, "")
    return o


def _fill(tpl: str, o: dict) -> str:
    return (tpl.replace("%%CALL%%", E(o["callsign"])).replace("%%NAME%%", E(o["name"]))
               .replace("%%QTH%%", E(o["qth"])).replace("%%GRID%%", E(o["grid"])))


def _split_call(call: str) -> str:
    """KR4OEO -> KR<em>4</em>OEO: accent the call-area digit."""
    for i, ch in enumerate(call):
        if ch.isdigit():
            return f"{E(call[:i])}<em>{E(ch)}</em>{E(call[i + 1:])}"
    return E(call)


def _qsl_card(o: dict) -> str:
    facts = []
    if o["qth"]:
        facts.append(E(o["qth"]) + (f" · {E(o['county'])} County" if o["county"] else ""))
    if o["grid"]:
        facts.append(f"Grid {E(o['grid'])}")
    if o["dmr_id"]:
        facts.append(f"DMR ID {E(o['dmr_id'])}")
    if o["email"]:
        facts.append(E(o["email"]))
    rows = "".join("<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>" for _ in range(4))
    waves = "".join(f'<circle cx="150" cy="40" r="{r}"/>' for r in (30, 52, 74, 96, 118, 140))
    size = {4: .95, 5: .9, 6: .78}.get(len(o["callsign"]), .66 if len(o["callsign"]) > 6 else .95)
    return f'''<div class="card">
  <svg class="waves" viewBox="0 0 200 200" aria-hidden="true">{waves}</svg>
  <div class="left">
    <h2 class="call" style="font-size:{size}in">{_split_call(o["callsign"])}</h2>
    <div class="name">{E(o["name"])}</div>
    <div class="facts">{"".join(f"<span>{f}</span>" for f in facts)}</div>
    <div class="bottom">
      <div class="line"><i>Rig</i><b></b></div>
      <div class="line"><i>Power</i><b></b></div>
      <div class="line"><i>Antenna</i><b></b></div>
    </div>
  </div>
  <div class="right">
    <div class="to">To radio<b></b></div>
    <div class="say">Confirming our contact</div>
    <table><thead><tr><th>Date</th><th>UTC</th><th>MHz</th><th>Mode</th><th>RST</th><th>2-way</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <div class="line"><i>Remarks</i><b></b></div>
    <div class="checks"><span>PSE QSL</span><span>TNX QSL</span><span>Via eQSL/LoTW</span></div>
    <div class="sig">73 de <em>{E(o["callsign"])}</em></div>
  </div>
  <div class="stripe"></div>
</div>'''


def _page(body: str) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            "</head><body>" + body + "</body></html>")


def _pdf(html_file: Path, pdf_file: Path, landscape: bool = False) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("PDF needs Playwright:  pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_file.resolve().as_uri())
        pg.wait_for_timeout(1200)
        pg.emulate_media(media="print")
        pg.pdf(path=str(pdf_file), format="Letter", landscape=landscape, print_background=True,
               prefer_css_page_size=True)
        b.close()


def write_qso(plan: Plan, outdir: Path, operator: dict, pdf: bool = False,
              templates: Path | None = None, rows: int = 24, theme: dict | None = None) -> list[Path]:
    """QSO_Log.html (printable), QSO_Log_Mobile.html (phone, CSV/ADIF export), QSL_Cards.html."""
    import json
    outdir.mkdir(parents=True, exist_ok=True)
    o = _op(operator)

    def tpl(name):
        own = templates / name if templates else None
        return (own if own and own.exists() else TEMPLATES / name).read_text(encoding="utf-8")

    files = []
    log_rows = "".join(f'<tr><td class="n">{i}</td><td></td><td></td><td></td><td></td><td class="rst"></td>'
                       f'<td class="rst"></td><td></td><td></td><td></td></tr>' for i in range(1, rows + 1))
    p = outdir / "QSO_Log.html"
    p.write_text(themed(_page(_fill(tpl("qso-log.html"), o).replace("%%ROWS%%", log_rows)), theme), encoding="utf-8")
    files.append(p)

    chans = {str(c.ch): [f"{c.freq:.4f}".rstrip("0").rstrip("."), c.name] for c in plan.channels}
    mobile = (_fill(tpl("qso-log-mobile.html"), o)
              .replace("%%OPERATOR_JSON%%", json.dumps({"callsign": o["callsign"], "grid": o["grid"]}))
              .replace("%%CHANNELS_JSON%%", json.dumps(chans, separators=(",", ":"))))
    p = outdir / "QSO_Log_Mobile.html"
    p.write_text(themed(_page(mobile), theme), encoding="utf-8")
    files.append(p)

    cards = "".join(_qsl_card(o) for _ in range(3))
    p = outdir / "QSL_Cards.html"
    p.write_text(themed(_page(_fill(tpl("qsl-card.html"), o).replace("%%CARDS%%", cards)), theme), encoding="utf-8")
    files.append(p)

    if pdf:
        for name, land in (("QSO_Log", True), ("QSL_Cards", False)):
            out = outdir / f"{name}.pdf"
            _pdf(outdir / f"{name}.html", out, landscape=land)
            files.append(out)
    return files
