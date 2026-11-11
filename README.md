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
1. **On GitHub** — Actions → **alain-scrape** → Run workflow. Scribd currently
   blocks GitHub's runner IPs (verified 2026-11-11), so this is a probe only.
2. **On your home PC** (the one that works) — clone this repo, then
   **double-click `run_alain.bat`**: Alain captures with your Edge, pushes the
   screenshots, and Bea stitches automatically a minute later. Ctrl+C stops
   Alain anytime; `run_alain.bat` again resumes where he left off.

## Where things land
- `screenshots/` — kept paper pages · `screenshots/review/` — suspects
- `PDFs/` — site-ready PDFs + `manifest.csv`

Note: GitHub pauses scheduled workflows after ~60 days with no repo activity —
any commit or manual run wakes them up again.
