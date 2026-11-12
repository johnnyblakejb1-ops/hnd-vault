# hnd-vault

Alain + Bea, living on GitHub — the cambook HND pipeline.

## The team
- **alain.py** — the Paper Camera (YOU pick, HE shoots). Opens Scribd in a
  visible window (your Edge), you open a paper, press ENTER, he screenshots
  every page into `screenshots/<docid>_<slug>_p<N>.png`, parks advert pages in
  `screenshots/review/`, and makes a preview PDF in `scribd_papers/`.
  Console: ENTER = shoot | goto URL | list | q. Ctrl+C is safe anytime.
- **alain_auto.py** — the robot mode (searches and follows links on its own,
  same filters). Used by the GitHub probe workflow.
- **stitch_papers.py** — "Bea". Stitches each document into one PDF on the
  cambook slightly-pink paper with a branded cover. Already-stitched docs are
  skipped by default; `--force` rebuilds everything.
- **.github/workflows/alain.yml** — twice-daily probe + on demand (robot mode;
  Scribd currently blocks GitHub runner IPs, verified 2026-11-11 — so the real
  capture happens at home).
- **.github/workflows/bea.yml** — fires on every screenshot push and after the
  probe: stitches new PDFs, commits them, uploads the `hnd-pdfs` artifact.

## Home-PC workflow (the one that works)
1. Clone this repo, double-click **`run_alain.bat`** (uses your Edge, no
   browser download).
2. In the browser: log into YOUR Scribd account once (optional — unlocks full
   docs; the login stays in `alain_profile/` and never leaves your PC).
3. Open a paper, press ENTER in the console, watch the pages fly by.
4. `q` to finish, then `capture.bat` (or let `run_alain.bat` do it) —
   screenshots go to GitHub and Bea stitches automatically.

## Where things land
- `screenshots/` — kept paper pages · `screenshots/review/` — suspects
- `scribd_papers/` — local preview PDFs (never uploaded) · `alain_profile/` —
  your Scribd login (never uploaded)
- `PDFs/` — site-ready branded PDFs + `manifest.csv`

Note: GitHub pauses scheduled workflows after ~60 days with no repo activity —
any commit or manual run wakes them up again.
