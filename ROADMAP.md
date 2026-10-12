# ham-fleet roadmap

Rough order, not promises. Ideas and pull requests welcome.

## Done
- [x] One channel list → CHIRP images/CSVs, DM32 NeonPlug, channel map, printable and phone cards
- [x] Plan validator (RX-only bands, AM air band, offsets, tones, names, duplicates)
- [x] RepeaterBook comparison (`rb-check`)
- [x] Radio settings with normalized names (`voice_prompt`, `key_beep`, `tx_timeout`...) across driver families
- [x] Separate `config/` (hand-edited), `radio-downloads/` (input) and `output/` folders; builds use each radio's latest download; `where` checks inputs

## Next
- [ ] **More output formats**
  - [ ] Export the plan as CSV, YAML and JSON (`ham-fleet export --format csv|yaml|json`) for spreadsheets and other tools
  - [ ] Per-radio "what got loaded" export in the same formats
  - [ ] Other programming tools' CSV formats (e.g. RT Systems, Anytone/OpenGD77 CPS) where there's demand
- [ ] `ham-fleet diff RADIO`: show what changes versus the radio's latest download before uploading
- [ ] `ham-fleet import FILE.csv --group NAME`: pull channels from a CHIRP/RepeaterBook CSV into channels.yaml
- [ ] Pin the CHIRP version (`chirp.lock`) so builds don't change when CHIRP updates
- [ ] DM32: DCS channels (needs a NeonPlug export with a DCS channel to learn the format)
- [ ] Normalized settings for more driver families (add them to `settings_catalog.py`)
- [ ] BF-888S example profile (16 channels, UHF only)

## Branding
- [ ] Logo for the README and GitHub social preview
- [ ] App icon (favicon for the web interface, container/registry icon), in SVG with PNG exports

## Docker image
- [ ] `Dockerfile`: python:3.12-slim + CHIRP checkout + ham-fleet; optional Playwright stage for PDFs
- [ ] Three mounts: `/config` and `/radio-downloads` (read-only for builds), `/output`; run as the host user (PUID/PGID)
- [ ] Publish to GHCR from GitHub Actions on each release tag

## Web interface (basic)
- [ ] Small FastAPI app over the same package, in the same container
- [ ] Channel table editor (edit/add/move), live validation, "Build" button with downloadable outputs, RepeaterBook check page
- [ ] channels.yaml stays the source of truth (the UI reads and writes it, so git history still works)
- [ ] Meant for a private network (e.g. Tailscale) or behind an authenticating proxy, not the open internet
