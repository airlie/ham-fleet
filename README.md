# ham-fleet

**One channel list → programming files for every radio you own.**

If you have a drawer full of handhelds (UV-5Rs, a few minis, a DMR radio, something with air band), keeping them all programmed the same way gets old fast. ham-fleet lets you keep a single `channels.yaml`, and builds the right files for each radio:

| Radio | What you get |
|---|---|
| Any [CHIRP](https://chirpmyradio.com)-supported radio you have a download of | A ready-to-upload `.img` built from **that radio's own image** (its calibration and settings carry over; pin the settings you care about), plus a CSV |
| Any radio without a download | A CHIRP CSV, from capabilities you describe (channel count, bands, AM, name length) |
| Baofeng DM32-UV | An updated [NeonPlug](https://neonplug.app) `.neonplug` export: your analog zones rebuilt, DMR channels and contacts untouched |
| Everyone | A master channel map CSV, a printable channel card (HTML/PDF) and a phone version with search |

Each channel keeps **the same number on every radio** that can hold it, and each radio only gets what it can actually do: a 128-channel radio gets the core plan, air band goes only to AM-capable radios, out-of-range channels are skipped and reported.

## Safety checks

`ham-fleet validate` (run automatically before every build) refuses to build when:
- an air band, NOAA weather, marine or railroad channel could transmit
- an air band channel isn't AM, or AM is used outside the air band
- a repeater has no offset, a CTCSS tone isn't a standard tone, a name is too long, or a channel number is used twice

It also warns on unusual offsets and toneless repeaters. CHIRP images are read back after writing. Nothing is ever uploaded automatically: you always upload in CHIRP or NeonPlug yourself.

## Install

Python 3.10+ on Linux, macOS or WSL.

```bash
git clone https://github.com/<you>/ham-fleet.git
cd ham-fleet
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
git clone --depth 1 https://github.com/kk7ds/chirp.git vendor/chirp   # CHIRP's radio drivers
pytest -q
```

CHIRP isn't on PyPI, so ham-fleet loads it from `vendor/chirp` (or `$HAM_FLEET_CHIRP`).

## Quick start

```bash
ham-fleet --home examples/demo build        # try the demo: builds two CSVs into examples/demo/output
ham-fleet init                              # create ./my-fleet with config/, radio-downloads/, output/ (git-ignored)
ham-fleet where                             # show the folders and which download each radio builds from
ham-fleet validate
ham-fleet list                              # radios in your fleet
ham-fleet list my-uv5r                      # exactly what one radio will get
ham-fleet settings my-uv5r                  # settings you can pin, with current values
ham-fleet build                             # build everything
ham-fleet build --only my-uv5r --dry-run -v
ham-fleet build --clean                     # remove old generated files first
ham-fleet cards --pdf                       # printable channel card + a phone version (PDF: pip install -e ".[pdf]" && playwright install chromium)
ham-fleet rb-check ~/Downloads/rb_*.csv     # compare your repeaters with RepeaterBook exports
```

## Folders: config, radio-downloads, output

ham-fleet keeps what you write, what you read from your radios and what it generates in three separate folders. `ham-fleet init` creates them:

```
my-fleet/                            ← "home" (git-ignored: it's yours, not the project's)
├── config/            hand-edited text
│   ├── channels.yaml                   the channel plan (the only place channels are edited)
│   ├── radios.yaml                     your radios, settings, optional paths
│   └── templates/                      optional card layouts (built-in defaults if absent)
├── radio-downloads/   INPUT: what you downloaded from each radio; ham-fleet only reads it
│   ├── my-uv5r/2026-10-01.img
│   ├── my-uv5r/2026-10-11.img          ← builds use the latest by name
│   └── dm32/2026-10-11.neonplug
└── output/            OUTPUT: generated, safe to delete (`build --clean`)
    ├── my-uv5r/UV-5R_Plan.img + .csv     one folder per radio id
    ├── dm32/DM32_Plan.neonplug
    ├── cards/                            printable + phone channel cards
    └── channel-map.csv
```

**Radio downloads.** Each build starts from the latest download in `radio-downloads/<radio id>/`, chosen by file name, so name them by date (`2026-10-11.img`). The radio's settings and calibration carry over into the built image, then the settings you list in radios.yaml are applied. So after changing something on a radio, save a fresh download before building. Older downloads stay as history; to build from a specific one, pin it with `base: 2026-10-01.img` in that radio's entry. `ham-fleet where` shows which file each radio will use.

**Finding the folders.** Each is found on its own, first match wins:

| Folder | Flag | Environment | radios.yaml | Default |
|---|---|---|---|---|
| home | `--home` | `HAM_FLEET_HOME` | | `./my-fleet`, else the bundled demo |
| config | `--config` | `HAM_FLEET_CONFIG` | | `<home>/config` |
| radio-downloads | `--downloads` | `HAM_FLEET_DOWNLOADS` | `paths: {downloads: …}` | `<home>/radio-downloads` |
| output | `--output` | `HAM_FLEET_OUTPUT` | `paths: {output: …}` | `<home>/output` |

`ham-fleet where` prints all of it and checks every radio has a download.

**In Docker** (planned) the same three folders become three mounts, the usual pattern for self-hosted containers:

```bash
docker run --rm \
  -v ./my-fleet/config:/config:ro \
  -v ./my-fleet/radio-downloads:/radio-downloads:ro \
  -v ./my-fleet/output:/output \
  ham-fleet build
```

`/config` and `/radio-downloads` can be read-only for builds (the planned web editor would need `/config` writable). Run the container as your own user (`--user $(id -u):$(id -g)`, or PUID/PGID on a NAS) so output files aren't owned by root.

`my-fleet/` is in `.gitignore`, so your plan, callsign and radio images never end up in this public repo. Give `config/` its own private repo if you want history.

### channels.yaml

Channels live in groups. A group becomes a block on the channel card, and optionally a DM32 zone.

```yaml
groups:
  - id: local
    title: Local repeaters
    card: table              # table | compact | air | none
    dm32_zone: Local Rptrs   # optional
    tier: core               # core (default) | ext
    channels:
      - {ch: 50, name: W1AW 2M, short: W1AW, freq: 146.94, duplex: '-', offset: 0.6, tone_mode: Tone, tone: 100.0, note: Newington}
      - {ch: 114, name: MAR 16, short: MAR16, freq: 156.8, power: Low, rx_only: true}
```

| Field | Meaning |
|---|---|
| `ch` | channel number, the same on every radio |
| `name` / `short` | 12-char name / 7-char name for small displays |
| `freq` | receive frequency in MHz |
| `duplex`, `offset` | `+`/`-` and MHz, for repeaters |
| `tone_mode` | `Tone` (encode), `TSQL` (encode + decode) or `DTCS`; with `tone:` or `dcs:` |
| `mode` | `FM` (default), `NFM`, `AM` |
| `power` | `High` (default) or `Low` |
| `rx_only` | transmit blocked |
| `scan_skip` | skipped while scanning |
| `note` | shown on the card |

### radios.yaml

```yaml
card_subtitle: "N0CALL"               # optional, shown on the channel cards
paths:                                # optional; see "Folders" above
  downloads: "/mnt/nas/radio-downloads"
radios:
  - id: my-uv5r
    label: UV-5R
    kind: chirp-image                  # builds from the latest radio-downloads/my-uv5r/*.img
    output: UV-5R_Plan                 # optional file name; defaults to the radio id
    tiers: [core]

  - id: td-h3
    kind: chirp-csv                    # no base image: describe the radio instead
    output: TD-H3_Plan
    tiers: [core, ext]
    groups: [frs, noaa, local, aviation]   # optional: only these groups
    remap: {aviation: 151}                 # optional: move a group to a new starting channel
    capabilities: {bounds: [1, 199], modes: [FM, NFM, AM], name_length: 8,
                   power: {Low: 2.0, High: 5.0}, bands: [[18.0, 600.0]]}

  - id: dm32
    kind: neonplug                     # builds from the latest radio-downloads/dm32/*.neonplug
    output: DM32_Plan
    tiers: [core]
    template_channel: "2m National Simp"   # an analog channel to copy settings from

  - id: sat-radio
    kind: chirp-image
    base: 2026-10-01.img               # optional: pin this download instead of the latest
    tiers: [core, ext]
    extra: {from_image: satellites.img, start: 601, named_only: true, scan_skip: true}   # in radio-downloads/sat-radio/
```

### Radio settings

Uploading a CHIRP image writes the radio's **settings** too, not just channels, so anything changed on the radio after its base image was saved gets reverted. List the settings you care about and they're applied on every build. Use the same names for every model; ham-fleet translates them into what each CHIRP driver calls them:

```yaml
presets:
  quiet: &quiet          # YAML anchor: define once, reuse on every radio
    voice_prompt: off
    key_beep: off
    tx_timeout: 60

radios:
  - id: my-uv5r
    kind: chirp-image
    settings: *quiet
```

| Setting | Values |
|---|---|
| `voice_prompt` | on / off |
| `voice_language` | english / chinese |
| `key_beep`, `roger_beep`, `dual_watch`, `battery_save`, `auto_key_lock`, `fm_radio`, `squelch_tail_elim` | on / off |
| `tx_timeout` | seconds (e.g. `60`), or `off` |
| `backlight` | seconds, or `always` |
| `squelch` | a level, or `off` (scale varies: UV-5R 0–9, UV-5R Mini/UV-32/UV-25 off/1–5) |
| `display` | `name` / `frequency` / `channel` (sets both A and B) |
| `scan_resume` | `time` / `carrier` / `search` |
| `vox` | `off`, or a level |

```bash
ham-fleet settings my-uv5r                 # which settings this radio supports, current values, CHIRP names
ham-fleet settings my-uv5r --raw           # every CHIRP setting, for anything not covered above
ham-fleet settings my-uv5r --image output/my-uv5r/UV-5R_Plan.img   # check a built image
```

A value the radio can't do (say `tx_timeout: 45` on a radio that steps by 15 s) stops the build with the options it does have. For model-specific settings, use the raw CHIRP name from `--raw` as the key (e.g. `settings.key1short: Flashlight`). The normalized names are mapped for the UV-5R and the UV-5R Mini / UV-32 / UV-25 (K5) driver families so far; adding another driver is a few lines in `ham_fleet/settings_catalog.py`.

Quirk: on the UV-5R, voice prompts and language share one setting, so `voice_prompt: off` wins over `voice_language`.

### Updating a radio

1. Edit `config/channels.yaml`, then run `ham-fleet validate` and `ham-fleet build`.
2. In CHIRP, **download from the radio first** and save it as `radio-downloads/<radio id>/<today's date>.img`, then build again so the image starts from the radio as it is now.
3. Open `output/<radio id>/….img` in CHIRP and upload it.
4. DM32: export from NeonPlug into `radio-downloads/dm32/` first, build, then import the built `.neonplug`, check it, and write.

## DM32 / NeonPlug notes

- Groups with a `dm32_zone` are "managed". Their channels sit as one block at the **end** of the DM32 channel list, and each build replaces that block and those zones. Everything else is left alone.
- If one of your own channels ends up after the managed block, the build stops and says which one.
- Not yet supported on the DM32: DCS channels and air band (the radio can't receive AM).
- The `.neonplug` format is unofficial, worked out from real exports. Keep an export of the radio before writing.

## Project layout

```
ham_fleet/       cli.py, paths.py (config/radio-downloads/output), model.py (YAML + channel selection), validate.py,
                 chirp_out.py, neonplug.py,
                 radio_settings.py + settings_catalog.py (normalized settings), rbcheck.py, cards.py
templates/       default card templates (printable and phone)
examples/demo/   demo config that builds without any radio downloads
tests/           pytest suite (CHIRP tests are skipped if vendor/chirp is missing)
```

## Use of AI

Nearly all of this project (code, tests and docs) was written by Claude, Anthropic's AI assistant, at my request. The DM32 `.neonplug` format was worked out by the AI from sample exports. Channel data comes from RepeaterBook and AirNav, but verify frequencies yourself before relying on them.

## Disclaimer

This is a hobby tool, not affiliated with CHIRP, Baofeng, TIDRADIO or NeonPlug. Check every file before uploading, and only transmit where your license and the radio's certification allow. FRS and GMRS, for example, require Part 95-certified radios in the US.

## License

GPL-3.0-or-later. ham-fleet uses CHIRP's drivers, which are GPLv3.
