"""ham-fleet - build programming files for a whole radio fleet from one channel list."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from . import __version__
from .model import channels_for, load_fleet, load_plan
from .validate import validate_plan

ROOT = Path(__file__).resolve().parent.parent


def config_dir(args) -> Path:
    """--config, then $HAM_FLEET_CONFIG, then ./my-fleet, then the bundled demo."""
    for cand in (args.config, os.environ.get("HAM_FLEET_CONFIG")):
        if cand:
            return Path(cand).expanduser().resolve()
    for cand in (Path.cwd() / "my-fleet", ROOT / "my-fleet"):
        if (cand / "channels.yaml").exists():
            return cand.resolve()
    return ROOT / "examples" / "demo"


def _load(args):
    cdir = config_dir(args)
    plan = load_plan(Path(args.channels) if args.channels else cdir / "channels.yaml")
    fleet = load_fleet(Path(args.radios) if args.radios else cdir / "radios.yaml",
                       backups=args.backups, output=args.out)
    return plan, fleet


def _report(issues, quiet_warn=False) -> int:
    errs = [i for i in issues if i.level == "error"]
    for i in issues:
        if i.level == "error" or not quiet_warn:
            print(i)
    print(f"{len(errs)} error(s), {len(issues) - len(errs)} warning(s)")
    return 1 if errs else 0


def cmd_where(args) -> int:
    cdir = config_dir(args)
    _, fleet = _load(args)
    print(f"config:  {cdir}\nbackups: {fleet.backups_dir}\noutput:  {fleet.output_dir}")
    return 0


def cmd_init(args) -> int:
    import shutil
    dest = Path(args.dest).expanduser().resolve()
    if (dest / "channels.yaml").exists():
        print(f"{dest} already has a channels.yaml; not overwriting.")
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    demo = ROOT / "examples" / "demo"
    for f in ("channels.yaml", "radios.yaml"):
        shutil.copy(demo / f, dest / f)
    (dest / "templates").mkdir(exist_ok=True)
    shutil.copy(ROOT / "templates" / "field-cards.html", dest / "templates" / "field-cards.html")
    print(f"Created {dest} from the demo. Edit channels.yaml and radios.yaml, then run: ham-fleet validate")
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
    path = Path(args.image) if args.image else fleet.backups_dir / r.base
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
    print(f"backups: {fleet.backups_dir}\noutput:  {fleet.output_dir}\n")
    for r in radios:
        if r.kind in ("chirp-image", "chirp-csv"):
            res = build_chirp(plan, r, fleet.backups_dir, fleet.output_dir, dry_run=args.dry_run)
        elif r.kind == "neonplug":
            res = build_neonplug(plan, r, fleet.backups_dir, fleet.output_dir, dry_run=args.dry_run)
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
            print(f"    -> {f.name}")
    if not args.dry_run and not args.only:
        _master_csv(plan, fleet.output_dir / "Master_Channel_Map.csv")
        print("    -> Master_Channel_Map.csv")
    return 0


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
    tdir = config_dir(args) / "templates"
    tpl = tdir / "field-cards.html"
    mtpl = tdir / "field-cards-mobile.html"
    air = None
    for r in fleet.radios:
        if "aviation" in r.remap:
            air = int(r.remap["aviation"])
    for f in write_cards(plan, fleet.output_dir, pdf=args.pdf, tdh3_air_start=air,
                         template=tpl if tpl.exists() else None):
        print(f"-> {f}")
    m = write_mobile(plan, fleet.output_dir, subtitle=fleet.card_subtitle, tdh3_air_start=air,
                     template=mtpl if mtpl.exists() else None,
                     desktop_template=tpl if tpl.exists() else None)
    print(f"-> {m}")
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
    p.add_argument("--config", help="config folder with channels.yaml and radios.yaml "
                   "(default: $HAM_FLEET_CONFIG, ./my-fleet, else the bundled demo)")
    p.add_argument("--channels", help="channel list (overrides <config>/channels.yaml)")
    p.add_argument("--radios", help="fleet definition (overrides <config>/radios.yaml)")
    p.add_argument("--backups", help="folder with radio backups (overrides radios.yaml / $FLEET_BACKUPS)")
    p.add_argument("--out", help="output folder (overrides radios.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a personal config folder from the demo")
    s.add_argument("dest", nargs="?", default="my-fleet")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("where", help="show which config folder is in use").set_defaults(fn=cmd_where)
    s = sub.add_parser("settings", help="list the settings you can use for a radio in radios.yaml")
    s.add_argument("radio")
    s.add_argument("filter", nargs="?", help="only names/labels containing this text, e.g. voice")
    s.add_argument("--image", help="read this image instead of the radio's base backup")
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
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("cards", help="build the printable channel card and the phone version")
    s.add_argument("--pdf", action="store_true", help="also make a PDF (needs Playwright)")
    s.set_defaults(fn=cmd_cards)

    s = sub.add_parser("rb-check", help="compare plan repeaters with RepeaterBook CSV exports")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_rbcheck)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
