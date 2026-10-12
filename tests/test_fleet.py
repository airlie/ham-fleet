import json
import zipfile
from pathlib import Path

import pytest

from ham_fleet.model import Channel, Group, Plan, RadioDef, channels_for, load_fleet, load_plan
from ham_fleet.validate import validate_plan
from ham_fleet.rbcheck import check, load_rb

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo" / "config"
PLAN = load_plan(DEMO / "channels.yaml")


def ch(**kw):
    base = dict(ch=1, name="TEST", short="TEST", freq=146.52, group="g", group_title="G")
    base.update(kw)
    return Channel(**base)


def plan_of(*chs, gid="g"):
    return Plan([Group(id=gid, title="G", channels=list(chs))])


def errors(plan):
    return [i for i in validate_plan(plan) if i.level == "error"]


def test_demo_plan_has_no_errors():
    assert errors(PLAN) == []


def test_unique_channel_numbers():
    nums = [c.ch for c in PLAN.channels]
    assert len(nums) == len(set(nums))


@pytest.mark.parametrize("bad,msg", [
    (dict(freq=121.5, mode="FM", rx_only=True), "air band must be AM"),
    (dict(freq=121.5, mode="AM", rx_only=False), "air band must be rx_only"),
    (dict(freq=162.55), "NOAA weather frequency must be rx_only"),
    (dict(freq=160.95), "railroad frequency must be rx_only"),
    (dict(freq=156.8), "marine frequency must be rx_only"),
    (dict(name="THIS NAME IS TOO LONG"), "name longer than 12"),
    (dict(tone_mode="Tone", tone=123.4), "not a standard CTCSS"),
    (dict(duplex="+", offset=0), "without an offset"),
    (dict(freq=146.0, mode="AM"), "AM outside the air band"),
])
def test_validator_catches(bad, msg):
    errs = errors(plan_of(ch(**bad)))
    assert any(msg in e.msg for e in errs), errs


def test_duplicate_channel_number():
    errs = errors(plan_of(ch(ch=5), ch(ch=5, name="OTHER")))
    assert any("more than once" in e.msg for e in errs)


def test_tiers_and_remap():
    fleet = load_fleet(DEMO / "radios.yaml")
    basic = channels_for(PLAN, fleet.radio("basic-handheld"))
    assert all(c.tier == "core" for _, c in basic)
    r = RadioDef(id="x", label="x", kind="chirp-csv", output="x", tiers=["core", "ext"], remap={"aviation": 151})
    air = [loc for loc, c in channels_for(PLAN, r) if c.group == "aviation"]
    assert air == [151, 152, 153]


def test_group_filter():
    r = RadioDef(id="x", label="x", kind="chirp-csv", output="x", tiers=["core", "ext"], groups=["noaa"])
    assert {c.group for _, c in channels_for(PLAN, r)} == {"noaa"}


def test_rbcheck_flags_wrong_tone_and_missing(tmp_path):
    rb = tmp_path / "rb.csv"
    rb.write_text("Location,Name,Frequency,Duplex,Offset,Tone,rToneFreq,cToneFreq,DtcsCode,DtcsPolarity,Mode,TStep,Comment\n"
                  '1,"W4XYZ",146.820000,-,0.6,Tone,203.5,88.5,023,NN,FM,5,"Somewhere",\n')
    p = plan_of(ch(ch=1, name="WRONGTONE", freq=146.82, duplex="-", offset=0.6, tone_mode="Tone", tone=136.5),
                ch(ch=2, name="GHOST", freq=444.0, duplex="+", offset=5.0, tone_mode="Tone", tone=100.0),
                ch(ch=3, name="GOOD", freq=146.82, duplex="-", offset=0.6, tone_mode="Tone", tone=203.5))
    out = check(p, load_rb([rb]))
    assert any(x.startswith("DIFFERENT") and "WRONGTONE" in x for x in out)
    assert any(x.startswith("NOT FOUND") and "GHOST" in x for x in out)
    assert not any("GOOD" in x for x in out)


def test_rbcheck_plain_export(tmp_path):
    rb = tmp_path / "rb.csv"
    rb.write_text('Output Freq,Input Freq,Offset,Uplink Tone,Downlink Tone,Call,"Location",County,State,Modes,Digital Access\n'
                  '146.850000,146.25000,-,131.8,,W1AW,"Town",County,State,FM ,\n')
    p = plan_of(ch(ch=1, name="OK", freq=146.85, duplex="-", offset=0.6, tone_mode="Tone", tone=131.8))
    assert check(p, load_rb([rb])) == []


# ---- tests that need CHIRP (skipped when vendor/chirp is missing)
def _have_chirp():
    try:
        from ham_fleet.chirp_out import chirp
        chirp()
        return True
    except SystemExit:
        return False


@pytest.mark.skipif(not _have_chirp(), reason="CHIRP not available (clone it into vendor/chirp)")
def test_chirp_csv_build(tmp_path):
    from ham_fleet.chirp_out import build_chirp
    fleet = load_fleet(DEMO / "radios.yaml")
    basic = build_chirp(PLAN, fleet.radio("basic-handheld"), DEMO, tmp_path)
    air = build_chirp(PLAN, fleet.radio("airband-handheld"), DEMO, tmp_path)
    btxt = (tmp_path / "Basic-Handheld.csv").read_text()
    atxt = (tmp_path / "Airband-Handheld.csv").read_text()
    assert "GUARD" not in btxt and "GUARD 121.5" in atxt
    assert "\n0," not in btxt
    assert air.written == basic.written + 3
    noaa = [l for l in atxt.splitlines() if "NOAA 1" in l][0]
    assert ",off," in noaa  # receive-only means TX inhibited


def _codeplug(tmp_path, channels, zones):
    cp = {"channels": channels, "zones": zones, "scanLists": [], "radioSettings": {"x": 1}, "exportDate": ""}
    p = tmp_path / "base.neonplug"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("codeplug.json", json.dumps(cp))
    return p


def test_neonplug_rebuild_is_idempotent(tmp_path):
    from ham_fleet.neonplug import build_neonplug, read_neonplug
    tmpl = {"number": 1, "name": "TEMPLATE", "mode": "Analog", "rxFrequency": 146.52, "txFrequency": 146.52,
            "forbidTx": False, "bandwidth": "25kHz", "power": "High", "txCtcssDcs": {"type": "None"},
            "rxCtcssDcs": {"type": "None"}, "scanAdd": False, "scanListId": 0}
    dig = dict(tmpl, number=2, name="DMR RPT", mode="Digital")
    _codeplug(tmp_path, [tmpl, dig], [{"id": "z1", "name": "Mine", "channels": [1, 2]}])
    radio = RadioDef(id="dm32", label="DM32", kind="neonplug", output="out1", tiers=["core"],
                     base="base.neonplug", template_channel="TEMPLATE")
    r1 = build_neonplug(PLAN, radio, tmp_path / radio.base, tmp_path)
    cp1 = read_neonplug(tmp_path / "out1.neonplug")
    radio2 = RadioDef(**{**radio.__dict__, "base": "out1.neonplug", "output": "out2"})
    build_neonplug(PLAN, radio2, tmp_path / radio2.base, tmp_path)
    cp2 = read_neonplug(tmp_path / "out2.neonplug")
    key = lambda cp: [(c["number"], c["name"], c["rxFrequency"], c["txFrequency"]) for c in cp["channels"]]
    assert key(cp1) == key(cp2)
    assert [z["name"] for z in cp1["zones"]] == [z["name"] for z in cp2["zones"]] == ["Mine", "Local Rptrs"]
    assert cp1["channels"][1]["name"] == "DMR RPT"          # untouched
    assert r1.written == 2
    rpt = [c for c in cp1["channels"] if c["name"] == "EXAMPLE 70CM"][0]
    assert rpt["txFrequency"] == 449.1
    assert rpt["txCtcssDcs"] == {"type": "CTCSS", "value": 123.0} and rpt["rxCtcssDcs"]["value"] == 123.0


def test_neonplug_refuses_unmanaged_channel_after_block(tmp_path):
    from ham_fleet.neonplug import build_neonplug
    tmpl = {"number": 1, "name": "TEMPLATE", "mode": "Analog", "rxFrequency": 146.52, "txFrequency": 146.52}
    managed = dict(tmpl, number=2, name="EXAMPLE 2M")
    stray = dict(tmpl, number=3, name="MY OWN")
    _codeplug(tmp_path, [tmpl, managed, stray], [{"id": "z", "name": "Local Rptrs", "channels": [2]}])
    radio = RadioDef(id="dm32", label="DM32", kind="neonplug", output="o", tiers=["core"],
                     base="base.neonplug", template_channel="TEMPLATE")
    with pytest.raises(SystemExit, match="not a clean block"):
        build_neonplug(PLAN, radio, tmp_path / radio.base, tmp_path)


@pytest.mark.skipif(not _have_chirp(), reason="CHIRP not available (clone it into vendor/chirp)")
def test_apply_settings():
    from chirp import settings as cs
    from ham_fleet.radio_settings import apply_settings, list_settings

    class FakeRadio:
        MODEL = "Fake"

        def __init__(self):
            self.saved = None
            self.voice = cs.RadioSetting("voice", "Voice", cs.RadioSettingValueList(["Off", "English"], current_index=1))
            self.beep = cs.RadioSetting("beep", "Beep", cs.RadioSettingValueBoolean(True))

        def get_settings(self):
            return cs.RadioSettings(cs.RadioSettingGroup("basic", "Basic", self.voice, self.beep))

        def set_settings(self, s):
            self.saved = s

    r = FakeRadio()
    log = apply_settings(r, {"voice": "off", "beep": False})
    assert r.voice.value.get_value() == "Off" and r.beep.value.get_value() is False
    assert log == ["voice: English -> Off", "beep: true -> false"] and r.saved is not None
    assert [n for n, *_ in list_settings(r, "voice")] == ["voice"]
    with pytest.raises(ValueError, match="not one of"):
        apply_settings(r, {"voice": "Klingon"})
    with pytest.raises(ValueError, match="unknown setting"):
        apply_settings(r, {"nope": 1})


def test_mobile_card_renders_every_channel():
    from ham_fleet.cards import render_mobile
    html = render_mobile(PLAN, subtitle="TEST")
    assert html.count('<li class="ch"') == len([c for g in PLAN.groups if g.card != "none" for c in g.channels])
    assert "%%" not in html and "TEST" in html and 'href="#g-local"' in html


def _fake(*settings):
    from chirp import settings as cs

    class FakeRadio:
        MODEL = "Fake"

        def __init__(self):
            self.saved = None
            self.items = list(settings)

        def get_settings(self):
            return cs.RadioSettings(cs.RadioSettingGroup("basic", "Basic", *self.items))

        def set_settings(self, s):
            self.saved = s
    return FakeRadio()


@pytest.mark.skipif(not _have_chirp(), reason="CHIRP not available (clone it into vendor/chirp)")
def test_normalized_settings_across_driver_styles():
    from chirp import settings as cs
    from ham_fleet.radio_settings import apply_settings, list_normalized
    RS, L, B = cs.RadioSetting, cs.RadioSettingValueList, cs.RadioSettingValueBoolean
    # UV-5R style
    uv5r = _fake(RS("voice", "Voice", L(["Off", "English", "Chinese"], current_index=1)),
                 RS("beep", "Beep", B(True)),
                 RS("timeout", "TOT", L(["15 sec", "30 sec", "60 sec", "120 sec"], current_index=3)),
                 RS("fmradio", "FM", B(True)),
                 RS("mdfa", "A", L(["Channel", "Name", "Frequency"], current_index=2)),
                 RS("mdfb", "B", L(["Channel", "Name", "Frequency"], current_index=2)))
    # K5 style (UV-5R Mini / UV-32 / UV-25)
    k5 = _fake(RS("settings.voicesw", "Enable Voice", B(True)),
               RS("settings.voice", "Voice", L(["English", "Chinese"], current_index=0)),
               RS("settings.beep", "Beep", L(["Off", "Beep", "Voice", "Both"], current_index=0)),
               RS("settings.tot", "TOT", L(["Off", "15 sec", "60 sec", "120 sec"], current_index=3)),
               RS("settings.fmenable", "Disable FM radio", B(False)),
               RS("settings.chadistype", "A", L(["Name", "Frequency", "Channel Number"], current_index=1)),
               RS("settings.chbdistype", "B", L(["Name", "Frequency", "Channel Number"], current_index=1)))
    want = {"voice_prompt": False, "key_beep": "on", "tx_timeout": 60, "fm_radio": "off", "display": "channel"}
    apply_settings(uv5r, want)
    apply_settings(k5, want)
    v = {s.get_name(): s.value.get_value() for s in uv5r.items}
    assert v == {"voice": "Off", "beep": True, "timeout": "60 sec", "fmradio": False,
                 "mdfa": "Channel", "mdfb": "Channel"}
    k = {s.get_name(): s.value.get_value() for s in k5.items}
    assert k["settings.voicesw"] is False and k["settings.beep"] == "Beep" and k["settings.tot"] == "60 sec"
    assert k["settings.fmenable"] is True            # "Disable FM radio" is inverted
    assert k["settings.chadistype"] == k["settings.chbdistype"] == "Channel Number"
    now = {n: c for n, _, c, _, _ in list_normalized(k5)}
    assert now["voice_prompt"] == "off" and now["key_beep"] == "on" and now["tx_timeout"] == "60"
    assert now["fm_radio"] == "off" and now["display"] == "channel"


@pytest.mark.skipif(not _have_chirp(), reason="CHIRP not available (clone it into vendor/chirp)")
def test_normalized_setting_errors():
    from chirp import settings as cs
    from ham_fleet.radio_settings import apply_settings
    r = _fake(cs.RadioSetting("timeout", "TOT", cs.RadioSettingValueList(["15 sec", "30 sec"], current_index=0)))
    with pytest.raises(ValueError, match="45 seconds is not available"):
        apply_settings(r, {"tx_timeout": 45})
    with pytest.raises(ValueError, match="no equivalent setting"):
        apply_settings(r, {"key_beep": "off"})
    with pytest.raises(ValueError, match="unknown setting"):
        apply_settings(r, {"made_up": 1})


def test_init_where_and_output_layout(tmp_path, capsys):
    from ham_fleet.cli import main
    home = tmp_path / "fleet"
    assert main(["init", str(home)]) == 0
    for p in ("config/channels.yaml", "config/radios.yaml",
              "config/templates/field-cards.html", "config/templates/field-cards-mobile.html",
              "radio-downloads/README.txt"):
        assert (home / p).exists(), p
    assert (home / "output").is_dir()
    assert main(["--home", str(home), "where"]) == 0
    out = capsys.readouterr().out
    assert "CONFIG" in out and "RADIO-DOWNLOADS" in out and "OUTPUT" in out and "basic-handheld/" in out
    if _have_chirp():
        assert main(["--home", str(home), "build"]) == 0
        assert (home / "output" / "basic-handheld" / "Basic-Handheld.csv").exists()
        assert (home / "output" / "channel-map.csv").exists()
        assert main(["--home", str(home), "build", "--clean", "--only", "basic-handheld"]) == 0
    assert main(["--home", str(home), "cards"]) == 0
    assert (home / "output" / "cards" / "Fleet_Field_Cards_Mobile.html").exists()


def test_separate_folders_and_paths_block(tmp_path, monkeypatch):
    from ham_fleet.paths import resolve
    for v in ("HAM_FLEET_HOME", "HAM_FLEET_CONFIG", "HAM_FLEET_DOWNLOADS", "HAM_FLEET_OUTPUT"):
        monkeypatch.delenv(v, raising=False)
    p = resolve(home=str(tmp_path))
    assert (p.config, p.downloads, p.output) == (tmp_path / "config", tmp_path / "radio-downloads",
                                                 tmp_path / "output")
    p = resolve(home=str(tmp_path), file_paths={"downloads": "/srv/radio", "output": "gen"})
    assert p.downloads == Path("/srv/radio") and p.output == tmp_path / "gen"
    monkeypatch.setenv("HAM_FLEET_OUTPUT", str(tmp_path / "env-out"))
    assert resolve(home=str(tmp_path)).output == tmp_path / "env-out"
    assert resolve(home=str(tmp_path), output=str(tmp_path / "cli")).output == tmp_path / "cli"   # CLI wins


def _one_radio_home(tmp_path, radio_yaml):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "channels.yaml").write_text((DEMO / "channels.yaml").read_text())
    (cfg / "radios.yaml").write_text(radio_yaml)
    return tmp_path


def test_where_flags_missing_download(tmp_path, capsys):
    from ham_fleet.cli import main
    home = _one_radio_home(tmp_path, "radios:\n  - id: r1\n    kind: chirp-image\n    tiers: [core]\n")
    assert main(["--home", str(home), "where"]) == 1
    assert "MISSING  r1/*.img" in capsys.readouterr().out


def test_latest_download_by_name_pin_and_extra(tmp_path):
    import os
    from ham_fleet.model import load_fleet
    from ham_fleet.paths import resolve
    home = _one_radio_home(tmp_path, "radios:\n  - id: r1\n    kind: chirp-image\n    tiers: [core]\n"
                                     "    extra: {from_image: sats.img, start: 601}\n")
    d = home / "radio-downloads" / "r1"
    d.mkdir(parents=True)
    for n in ("2026-10-01.img", "2026-10-11.img", "sats.img", "notes.txt"):
        (d / n).write_text("x")
    os.utime(d / "2026-10-11.img", (1, 1))          # file times don't matter, names do
    fleet = load_fleet(home / "config" / "radios.yaml", resolve(home=str(home)))
    r = fleet.radio("r1")
    assert fleet.base_file(r).name == "2026-10-11.img"
    assert fleet.extra_file(r).name == "sats.img"
    r.base = "2026-10-01.img"                        # pinned
    assert fleet.base_file(r).name == "2026-10-01.img"


def test_qso_log_and_qsl_cards(tmp_path):
    from ham_fleet.cards import write_qso
    files = write_qso(PLAN, tmp_path, {"callsign": "n0call", "name": "Pat", "qth": "Anytown, KS", "grid": "EM17"})
    names = {f.name for f in files}
    assert names == {"QSO_Log.html", "QSO_Log_Mobile.html", "QSL_Cards.html"}
    log = (tmp_path / "QSO_Log.html").read_text()
    assert "N0CALL" in log and log.count('<td class="n">') == 24 and "%%" not in log
    qsl = (tmp_path / "QSL_Cards.html").read_text()
    assert qsl.count('class="card"') == 3 and "N<em>0</em>CALL" in qsl and "Anytown, KS" in qsl
    mob = (tmp_path / "QSO_Log_Mobile.html").read_text()
    assert '"callsign": "N0CALL"' in mob and '"44":["446","70CM CALL"]' in mob and "%%" not in mob


def test_qso_without_operator_block(tmp_path):
    from ham_fleet.cards import write_qso
    write_qso(PLAN, tmp_path, {})
    assert "N0CALL" in (tmp_path / "QSL_Cards.html").read_text()


def test_theme_accent_applies_to_every_printable(tmp_path):
    from ham_fleet.cards import theme_css, write_cards, write_mobile, write_qso
    theme = {"accent": "ba0c2f"}
    css = theme_css(theme)
    assert "--accent:#BA0C2F" in css and "prefers-color-scheme:dark" in css and "@media print" in css
    files = write_cards(PLAN, tmp_path, theme=theme) + [write_mobile(PLAN, tmp_path, theme=theme)] \
        + write_qso(PLAN, tmp_path, {"callsign": "N0CALL"}, theme=theme)
    for f in files:
        t = f.read_text()
        assert 'id="ham-fleet-theme"' in t and t.index("ham-fleet-theme") < t.index("</body>"), f.name
    assert theme_css({}) == "" and theme_css(None) == ""
    with pytest.raises(SystemExit, match="not a #RRGGBB"):
        theme_css({"accent": "red"})
