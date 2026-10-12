"""ham-fleet - build programming files for a whole radio fleet from one channel list."""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .model import BASE_EXT, channels_for, load_fleet, load_plan, read_radios_yaml
from .paths import ROOT, resolve
from .validate import validate_plan


def _paths(args):
    """Resolve config / radio-downloads / output (radios.yaml may hold a `paths:` block)."""
    first = resolve(args.home, args.config, args.downloads, args.output)
    radios_file = Path(args.radios) if args.radios else first.radios_file
    data = read_radios_yaml(radios_file) if radios_file.exists() else {}
    return resolve(args.home, args.config, args.downloads, args.output, data.get("paths")), radios_file, data


def _load(args):
    paths, radios_file, data = _paths(args)
    if not paths.channels_file.exists() and not args.channels:
        raise SystemExit(f"No channels.yaml in {paths.config}. Run `ham-fleet init` or pass --home/--config.")
    plan = load_plan(Path(args.channels) if args.channels else paths.channels_file)
    fleet = load_fleet(radios_file, paths, data)
    return plan, fleet


def _report(issues, quiet_warn=False) -> int:
    errs = [i for i in issues if i.level == "error"]
    for i in issues:
        if i.level == "error" or not quiet_warn:
            print(i)
    print(f"{len(errs)} error(s), {len(issues) - len(errs)} warning(s)")
    return 1 if errs else 0


def cmd_where(args) -> int:
    plan, fleet = _load(args)
    p = fleet.paths
    w = max([len(r.id) for r in fleet.radios] + [12]) + 1
    print(f"home             {p.home}")
    print(f"\nCONFIG           {p.config}")
    print(f"  channels.yaml  {len(plan.channels)} channels in {len(plan.groups)} groups")
    print(f"  radios.yaml    {len(fleet.radios)} radios")
    for t in ("field-cards.html", "field-cards-mobile.html"):
        print(f"  templates/{t:<24} {'yours' if (p.templates / t).exists() else 'built-in default'}")
    print(f"\nRADIO-DOWNLOADS  {p.downloads}{'' if p.downloads.is_dir() else '   (not created yet)'}")
    print(f"  {'radio':<{w}} build starts from")
    problems = 0
    for r in fleet.radios:
        if r.kind not in BASE_EXT:
            print(f"  {r.id:<{w}} (nothing needed: {r.kind})")
            continue
        f = fleet.base_file(r)
        if f is None or not f.exists():
            problems += 1
            want = r.base or f"*{BASE_EXT[r.kind]}"
            print(f"  {r.id:<{w}} MISSING  {r.id}/{want}")
            continue
        how = "pinned in radios.yaml" if r.base else "latest by name"
        print(f"  {r.id:<{w}} {r.id}/{f.name}  ({how})")
        x = fleet.extra_file(r)
        if x is not None:
            ok = x.exists()
            problems += not ok
            print(f"  {'':<{w}} {'+' if ok else 'MISSING'} {r.id}/{x.name}  (extra)")
    print(f"\nOUTPUT           {p.output}")
    for r in fleet.radios:
        kind = {"neonplug": ".neonplug", "chirp-image": ".img + .csv"}.get(r.kind, ".csv")
        print(f"  {r.id + '/':<{w + 1}}{r.output}{kind}")
    print(f"  {'cards/':<{w + 1}}Fleet_Field_Cards.html (.pdf), Fleet_Field_Cards_Mobile.html")
    print(f"  channel-map.csv  every channel in one table")
    if problems:
        print(f"\n{problems} radio download(s) missing: save each radio's download in "
              f"{p.downloads}/<radio id>/")
    return 1 if problems else 0


DOWNLOADS_README = """Radio downloads: the input for each build. One folder per radio id from radios.yaml:

    radio-downloads/
      my-uv5r/2026-10-11.img          CHIRP: Radio > Download, then File > Save As
      dm32/2026-10-11.neonplug        NeonPlug: Export

Each build starts from the LATEST file in the radio's folder, by name (its settings and calibration
carry over). Name downloads by date (2026-10-11.img) so the latest sorts last, and save a fresh one
whenever you change something on the radio. Older files stay as history. To use a specific file
instead, pin it in radios.yaml:  base: 2026-10-01.img

ham-fleet only reads this folder; it never changes or deletes anything here.
"""


def cmd_init(args) -> int:
    home = Path(args.dest).expanduser().resolve()
    cfg = home / "config"
    if (cfg / "channels.yaml").exists():
        print(f"{cfg} already has a channels.yaml; not overwriting.")
        return 1
    demo = ROOT / "examples" / "demo" / "config"
    (cfg / "templates").mkdir(parents=True, exist_ok=True)
    for f in ("channels.yaml", "radios.yaml"):
        shutil.copy(demo / f, cfg / f)
    for t in ("field-cards.html", "field-cards-mobile.html"):
        shutil.copy(ROOT / "templates" / t, cfg / "templates" / t)
    (home / "radio-downloads").mkdir(exist_ok=True)
    (home / "radio-downloads" / "README.txt").write_text(DOWNLOADS_README, encoding="utf-8")
    (home / "output").mkdir(exist_ok=True)
    print(f"Created {home}:")
    print("  config/channels.yaml           your channel plan")
    print("  config/radios.yaml             your radios")
    print("  config/templates/              card layouts (optional to edit)")
    print("  radio-downloads/<radio id>/    save each radio's CHIRP/NeonPlug download here")
    print("  output/                        generated files")
    print("Next: ham-fleet where   (checks everything is found)")
    return 0


def cmd_settings(args) -> int:
    from .chirp_out import chirp
    from .radio_settings import list_normalized, list_settings
    _, fleet = _load(args)
    r = fleet.radio(args.radio)
    if r.kind != "chirp-image":
        print(f"{r.id} is {r.kind}; settings are only managed for chirp-image radios")
        return 1
    directory, _, _ = chirp()
    path = Path(args.image) if args.image else fleet.base_file(r)
    if path is None or not path.exists():
        print(f"No radio download for {r.id}: save one in radio-downloads/{r.id}/ or pass --image")
        return 1
    radio = directory.get_radio_by_image(str(path))
    print(f"{r.id}: {radio.VENDOR} {radio.MODEL}  ({path.name})\n")
    flt = (args.filter or "").lower()
    if args.raw:
        rows = list_settings(radio, flt)
        w = max((len(n) for n, *_ in rows), default=10)
        for name, label, cur, allowed in rows:
            mark = "*" if name in r.settings else " "
            print(f"{mark} {name:<{w}}  {cur:<14} {label}  [{allowed}]")
    else:
        rows = [x for x in list_normalized(radio) if flt in (x[0] + x[4]).lower()]
        print(f"  {'setting':<18} {'now':<10} {'values':<28} CHIRP name on this radio")
        for name, values, cur, maps, help_ in rows:
            mark = "*" if name in r.settings else " "
            print(f"{mark} {name:<18} {cur:<10} {values:<28} {maps}")
        print("\nUse these names under settings: in radios.yaml. "
              "--raw lists every CHIRP setting, for model-specific ones.")
    if r.settings:
        print("* = set in radios.yaml")
    return 0


def cmd_validate(args) -> int:
    plan, _ = _load(args)
    return _report(validate_plan(plan))


def cmd_list(args) -> int:
    plan, fleet = _load(args)
    if not args.radio:
        print(f"{'id':<12} {'kind':<12} label")
        for r in fleet.radios:
            print(f"{r.id:<12} {r.kind:<12} {r.label}")
        print(f"\n{len(plan.channels)} channels in {len(plan.groups)} groups")
        return 0
    r = fleet.radio(args.radio)
    for loc, c in channels_for(plan, r):
        print(f"{loc:>4}  {c.name:<13} {c.freq:9.4f} {c.duplex or ' '}{c.offset or '':<4} "
              f"{c.tone_mode:<5} {c.mode:<4} {'RX' if c.rx_only else ''}")
    return 0


def cmd_build(args) -> int:
    from .chirp_out import build_chirp
    from .neonplug import build_neonplug
    plan, fleet = _load(args)
    if _report(validate_plan(plan), quiet_warn=True):
        print("Fix the errors above before building.")
        return 1
    radios = [fleet.radio(x) for x in args.only] if args.only else fleet.radios
    print(f"config: {fleet.paths.config}\noutput: {fleet.output_dir}\n")
    if args.clean and not args.dry_run:
        _clean(fleet, radios)
    for r in radios:
        out = fleet.radio_out(r)
        if r.kind in ("chirp-image", "chirp-csv"):
            src = fleet.base_file(r)
            if src is not None and src.exists():
                print(f"{r.id}: from radio-downloads/{r.id}/{src.name}")
            res = build_chirp(plan, r, src, out, dry_run=args.dry_run, extra_src=fleet.extra_file(r))
        elif r.kind == "neonplug":
            src = fleet.base_file(r)
            if src is not None and src.exists():
                print(f"{r.id}: from radio-downloads/{r.id}/{src.name}")
            res = build_neonplug(plan, r, src, out, dry_run=args.dry_run)
        else:
            print(f"{r.id}: unknown kind '{r.kind}'")
            return 1
        print(res.summary())
        for chg in getattr(res, "settings_changed", []):
            print(f"    setting {chg}")
        if args.verbose:
            for s in res.skipped:
                print(f"    skipped {s}")
        for f in res.files:
            print(f"    -> {f.relative_to(fleet.output_dir)}")
    if not args.dry_run and not args.only:
        _master_csv(plan, fleet.output_dir / "channel-map.csv")
        print("    -> channel-map.csv")
    return 0


GENERATED = {".img", ".csv", ".neonplug", ".html", ".pdf"}


def _clean(fleet, radios) -> None:
    """Remove previously generated files (only known output types, only inside the output folder)."""
    n = 0
    for r in radios:
        d = fleet.radio_out(r)
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file() and f.suffix in GENERATED:
                    f.unlink()
                    n += 1
    print(f"cleaned {n} old file(s)\n")


def _master_csv(plan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Ch", "Name", "Short", "RX MHz", "Duplex", "Offset", "Tone mode", "Tone/DCS", "Mode",
                    "Power", "TX", "Group", "Tier", "Note"])
        for c in plan.channels:
            tv = c.dcs if c.tone_mode == "DTCS" else (c.tone if c.tone_mode else "")
            w.writerow([c.ch, c.name, c.short, f"{c.freq:.4f}", c.duplex, c.offset or "", c.tone_mode, tv,
                        c.mode, c.power, "RX only" if c.rx_only else "yes", c.group_title, c.tier, c.note])


def cmd_cards(args) -> int:
    from .cards import write_cards, write_mobile
    plan, fleet = _load(args)
    tdir = fleet.paths.templates
    tpl = tdir / "field-cards.html"
    mtpl = tdir / "field-cards-mobile.html"
    air = None
    for r in fleet.radios:
        if "aviation" in r.remap:
            air = int(r.remap["aviation"])
    for f in write_cards(plan, fleet.cards_out, pdf=args.pdf, tdh3_air_start=air,
                         template=tpl if tpl.exists() else None, theme=fleet.theme):
        print(f"-> {f}")
    m = write_mobile(plan, fleet.cards_out, subtitle=fleet.card_subtitle, tdh3_air_start=air,
                     template=mtpl if mtpl.exists() else None,
                     desktop_template=tpl if tpl.exists() else None, theme=fleet.theme)
    print(f"-> {m}")
    from .cards import write_qso
    for f in write_qso(plan, fleet.cards_out, fleet.operator, pdf=args.pdf, templates=tdir, theme=fleet.theme):
        print(f"-> {f}")
    if not fleet.operator.get("callsign"):
        print("tip: add an `operator:` block (callsign, name, qth, grid) to radios.yaml for the QSO log and QSL cards")
    return 0


def cmd_rbcheck(args) -> int:
    from .rbcheck import check, load_rb
    plan, _ = _load(args)
    entries = load_rb([Path(p) for p in args.files])
    lines = check(plan, entries)
    for ln in lines:
        print(ln)
    print(f"{len(entries)} RepeaterBook entries read; {len(lines)} plan repeater(s) to review")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ham-fleet", description=__doc__)
    p.add_argument("--version", action="version", version=f"ham-fleet {__version__}")
    p.add_argument("--home", help="folder holding config/, radio-downloads/ and output/ "
                   "(default: $HAM_FLEET_HOME, ./my-fleet, else the bundled demo)")
    p.add_argument("--config", help="config folder (default: $HAM_FLEET_CONFIG or <home>/config)")
    p.add_argument("--downloads", help="radio downloads folder (default: $HAM_FLEET_DOWNLOADS or <home>/radio-downloads)")
    p.add_argument("--output", "--out", dest="output",
                   help="output folder (default: $HAM_FLEET_OUTPUT or <home>/output)")
    p.add_argument("--channels", help="use this channels.yaml instead of <config>/channels.yaml")
    p.add_argument("--radios", help="use this radios.yaml instead of <config>/radios.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create config/, radio-downloads/ and output/ from the demo")
    s.add_argument("dest", nargs="?", default="my-fleet")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("where", help="show the folders and which radio download each build will use")\
        .set_defaults(fn=cmd_where)

    s = sub.add_parser("settings", help="list the settings you can use for a radio in radios.yaml")
    s.add_argument("radio")
    s.add_argument("filter", nargs="?", help="only names/labels containing this text, e.g. voice")
    s.add_argument("--image", help="read this image instead of the radio's latest download")
    s.add_argument("--raw", action="store_true", help="list every CHIRP setting with its driver-specific name")
    s.set_defaults(fn=cmd_settings)

    sub.add_parser("validate", help="check the channel list for mistakes").set_defaults(fn=cmd_validate)

    s = sub.add_parser("list", help="list radios, or what one radio will get")
    s.add_argument("radio", nargs="?")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("build", help="build images, CSVs and the DM32 file")
    s.add_argument("--only", nargs="+", metavar="RADIO", help="build just these radio ids")
    s.add_argument("--dry-run", action="store_true", help="show what would be written")
    s.add_argument("-v", "--verbose", action="store_true", help="list skipped channels")
    s.add_argument("--clean", action="store_true", help="delete old generated files for these radios first")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("cards", help="build channel cards, QSO log sheets and QSL cards (printable + phone)")
    s.add_argument("--pdf", action="store_true", help="also make a PDF (needs Playwright)")
    s.set_defaults(fn=cmd_cards)

    s = sub.add_parser("rb-check", help="compare plan repeaters with RepeaterBook CSV exports")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_rbcheck)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
