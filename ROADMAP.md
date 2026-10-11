# ham-fleet roadmap

## 0.1 — CLI (done)
- One channel list → CHIRP images/CSVs, DM32 NeonPlug, master CSV, field cards
- Validator, RepeaterBook check, pytest suite

## 0.2 — Quality of life
- [ ] `ham-fleet diff RADIO` — show what changes versus the radio's current backup before uploading
- [ ] `ham-fleet import-chirp FILE.csv --group NAME` — pull channels from a CHIRP/RepeaterBook CSV into channels.yaml
- [ ] Pin the CHIRP commit in a `chirp.lock` file so builds don't change when CHIRP updates
- [ ] DCS support for the DM32 writer (needs one NeonPlug export with a DCS channel to learn the format)
- [ ] BF-888S example profile (16 channels, UHF only)

## 0.3 — Docker
- [ ] `Dockerfile`: python:3.12-slim + CHIRP checkout + ham-fleet; Playwright stage optional for PDFs
- [ ] Run on a NAS: mount the backups folder read-only and an output folder, e.g.
      `docker run --rm -v /volume1/radio/backups:/backups:ro -v /volume1/radio/out:/out ham-fleet build`
- [ ] GitHub Actions: build and push the image to GHCR on tag

## 0.4 — Web UI
- [ ] Small FastAPI app over the same package: channel table editor (edit/add/move), live validation,
      "Build" button that offers the output files for download, RepeaterBook check page
- [ ] Runs in the same container; reachable over a private network (e.g. Tailscale) or a tunnel
- [ ] channels.yaml stays the source of truth (the UI reads and writes it, so git history still works)
