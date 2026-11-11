# hnd-vault

Alain + Bea, living on GitHub — the cambook HND pipeline that runs itself.

- **alain.py** — walks Scribd, screenshots HND past papers, and parks advert/junk
  pages in `screenshots/review/` (nothing is ever deleted). Env overrides:
  `ALAIN_MAX_LINKS`, `ALAIN_PAGES_PER_DOC`, `ALAIN_TIME_CAP` (minutes).
- **stitch_papers.py** — "Bea". Stitches each document into one PDF on the
  cambook slightly-pink paper with a branded cover. Already-stitched docs are
  skipped by default; `--force` rebuilds everything.
- **.github/workflows/alain.yml** — twice a day (04:30 & 16:30 Lagos time) and on
  demand: installs Chromium, runs Alain, commits new screenshots.
- **.github/workflows/bea.yml** — after every Alain run and on demand: stitches
  new PDFs, commits them, uploads the `hnd-pdfs` artifact.

## Two ways Alain captures
1. **On GitHub** — Actions → **alain-scrape** → Run workflow → set `max_links` to 3
   for a first drive. Works only if Scribd accepts GitHub's runner IPs (test it).
2. **On your home PC** (always works) — clone this repo, run `python alain.py`
   inside it, then double-click **capture.bat**. Bea stitches automatically.

## Where things land
- `screenshots/` — kept paper pages · `screenshots/review/` — suspects
- `PDFs/` — site-ready PDFs + `manifest.csv`

Note: GitHub pauses scheduled workflows after ~60 days with no repo activity —
any commit or manual run wakes them up again.
