"""
Alain — Scribd document screenshotter (UNLIMITED + FOCUSED + SEARCH MODE, v2)
-----------------------------------------------------------------------------
Alain works completely on his own:
  1. SEARCHES Scribd for your keywords and stocks his queue with results
  2. Opens each document, scrolls the viewer, screenshots every page
  3. Finds links to other on-topic documents, visits them, and repeats
  4. NEVER STOPS until you press Ctrl+C

NEW IN V2 — Alain learned to tell papers from jargon:
  1. TITLE BOUNCER: documents titled like guides/brochures/adverts
     ("hda-hnd-progression-guide", "admission brochure"...) never enter the queue.
  2. PAGE JUDGE: before keeping a screenshot he reads the page's own text
     (free — no OCR needed). Adverts talk about "university, admission, IELTS,
     www" — real papers talk about "instructions, answer all, paper, marks".
     Suspect pages go to screenshots/review/ — NOTHING is ever deleted.
  3. If a page has no text layer (pure scan), he judges the picture instead:
     colourful = flyer, mostly plain = paper.
  4. Resume still works — docs already captured (even only in review/) are skipped.

Setup (one time):
    pip install playwright pillow
    playwright install chromium
    (On GitHub Actions the workflows do all of this automatically.)

Run:
    python alain.py
Tip: set MAX_LINKS_TO_FOLLOW = 5 for a first test drive, watch how many pages
land in review/ vs main folder, then put it back to 0.
"""

import os
import random
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ================= SETTINGS (edit these) =================
START_URL = "https://www.scribd.com/document/819844284/hnd-2023-CSN-Past-questions"
PAGE_SELECTOR = ".outer_page"    # CSS selector for one document page
PAGES_PER_DOC = 0                # 0 = EVERY page | 1, 2, 3... = just that many
MAX_LINKS_TO_FOLLOW = 0          # 0 = NO LIMIT, all links forever! | 10, 20... = cap it
SEARCH_QUERIES = [               # Alain searches Scribd for these FIRST
    "hnd past questions",
    "hnd past questions cameroon",
    "hnd past paper",
]
IDLE_PATIENCE = 5                # 'still nothing new?' checks before Alain stops scrolling
OUTPUT_DIR = Path("screenshots")
REVIEW_DIR = OUTPUT_DIR / "review"   # suspect pages land here (never deleted)
HEADLESS = True                  # False = watch Alain work on your screen
DELAY_SECONDS = 5                # pause between documents (bigger = safer)
JITTER_SECONDS = 2               # random 0-2s added to each pause (less robotic)

# ---- GitHub Actions overrides (env vars beat the settings above) ----
MAX_LINKS_TO_FOLLOW = int(os.environ.get("ALAIN_MAX_LINKS", MAX_LINKS_TO_FOLLOW))
PAGES_PER_DOC = int(os.environ.get("ALAIN_PAGES_PER_DOC", PAGES_PER_DOC))
TIME_CAP_MINUTES = float(os.environ.get("ALAIN_TIME_CAP", "0"))   # 0 = no time cap
BROWSER_CHANNEL = os.environ.get("ALAIN_BROWSER_CHANNEL", "")    # e.g. "msedge" = reuse your Edge

# ---- v2 filters (edit freely) ----
REQUIRED_KEYWORDS = ["hnd"]      # topic: document title must contain one of these
JUNK_TITLE_WORDS = [             # titles with any of these = guide/advert, not a paper
    "guide", "brochure", "admission", "admissions", "progression", "prospectus",
    "syllabus", "timetable", "result", "results", "flyer", "poster",
    "scholarship", "project", "textbook", "handout", "notes", "summary",
    "top-up", "topup", "requirements", "course-outline",
]
TITLE_MUST_HAVE = []             # optional extra strictness, e.g.
                                 # ["past", "question", "exam", "paper"]
FILTER_PAGES = True              # True = Alain judges every page before keeping it

JUNK_PAGE_WORDS = [              # the vocabulary of adverts
    "university", "admission", "apply now", "apply here", "ielts", "scholarship",
    "tuition", "study abroad", "campus", "www.", "http", "whatsapp", "click here",
    "follow us", "subscribe", "sign up", "enrol", "brochure", "telegram",
    "facebook", "instagram", "tutorials", "register now", "hotline", "call now",
]
EXAM_PAGE_WORDS = [              # the vocabulary of real papers
    "question", "paper", "answer", "instruction", "marks", "section",
    "candidate", "examination", "diploma", "hnd", "semester", "time allowed",
    "duration", "ministry", "republic", "subject", "series",
]
# =========================================================

DOCUMENT_LINK = re.compile(r"^https?://(?:www\.)?scribd\.com/document/(\d+)")


def doc_id_from(url):
    m = re.search(r"/document/(\d+)", url)
    return m.group(1) if m else None


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60] or "doc"


def title_from_url(url):
    """Pull the document's real name out of its URL."""
    m = re.search(r"/document/\d+/([^/?#]+)", url)
    if m and m.group(1):
        return slugify(m.group(1))
    return "doc"


def word_hit(word, name):
    """Does `word` start any hyphen-separated chunk of `name`?"""
    return ("-" + word) in ("-" + name)


def matches_filter(url):
    """v2 bouncer: on-topic, not junk-titled, (optionally) must contain a keyword."""
    name = title_from_url(url)
    if REQUIRED_KEYWORDS and not any(
        word_hit(kw.lower().replace(" ", "-"), name) for kw in REQUIRED_KEYWORDS
    ):
        return False
    if any(word_hit(w, name) for w in JUNK_TITLE_WORDS):
        return False
    if TITLE_MUST_HAVE and not any(word_hit(w, name) for w in TITLE_MUST_HAVE):
        return False
    return True


def picture_is_junk(png_path):
    """No text layer? Judge the picture: colourful or dark = advert/flyer."""
    try:
        from PIL import Image
    except ImportError:
        return False  # pillow missing -> can't judge, keep the page (fail-safe)
    try:
        img = Image.open(png_path).convert("RGB").resize((110, 154))
    except Exception:
        return False
    px = list(img.getdata())
    n = len(px)
    color = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 45)
    light = sum(1 for r, g, b in px if min(r, g, b) > 170 and max(r, g, b) - min(r, g, b) < 45)
    return (color / n) > 0.06 or (light / n) < 0.35


def looks_like_junk(txt, png_path):
    """Returns a reason string if the page smells like an advert, '' if it's a keeper."""
    t = (txt or "").strip().lower()
    if len(t) >= 25:
        junk = sum(1 for w in JUNK_PAGE_WORDS if w in t)
        exam = sum(1 for w in EXAM_PAGE_WORDS if w in t)
        words = len(t.split())
        if junk >= 2:
            return f"advert words x{junk}"
        if exam == 0 and (junk >= 1 or words < 60):
            return "talks like an advert, not an exam"
        return ""
    if picture_is_junk(png_path):
        return "colourful picture page, not a text paper page"
    return ""


def embed_url(doc_id):
    return f"https://www.scribd.com/embeds/{doc_id}/content?start_page=1"


def already_captured(doc_id):
    """True if screenshots of this document already exist (resume superpower)."""
    return any(OUTPUT_DIR.glob(f"{doc_id}_*")) or any(REVIEW_DIR.glob(f"{doc_id}_*"))


def harvest_links(hrefs, seen, queued_ids):
    """Turn a pile of raw hrefs into a deduped, on-topic, brand-new shortlist."""
    fresh = []
    ignored = 0
    for h in hrefs:
        h = h.split("?")[0].split("#")[0]
        m = DOCUMENT_LINK.match(h)
        if not m:
            continue
        lid = m.group(1)
        if lid in seen or lid in queued_ids:
            continue
        if not matches_filter(h):     # off-topic or junk-titled? Alain shrugs and moves on
            ignored += 1
            continue
        fresh.append(h)
        queued_ids.add(lid)
    return fresh, ignored


def search_scribd(page, query, seen, queued_ids):
    """Alain searches Scribd directly instead of waiting for lucky links."""
    url = f"https://www.scribd.com/search?query={query.replace(' ', '+')}"
    print(f"\n[search] Alain hunts for: '{query}'")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    for _ in range(4):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)

    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    fresh, ignored = harvest_links(hrefs, seen, queued_ids)
    note = f" ({ignored} junk/off-topic bounced)" if ignored else ""
    print(f"   found {len(fresh)} on-topic document(s){note}")
    return fresh


def screenshot_document(page, doc_id, pages_to_grab, doc_name):
    """Alain opens a document in the embed viewer and screenshots its pages.
    v2: every page is judged first — adverts/blank pages go to review/."""
    page.goto(embed_url(doc_id), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector(PAGE_SELECTOR, timeout=30000)

    # Wait until page 1 has actually finished rendering (images loaded)
    try:
        page.wait_for_function(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const imgs = el.querySelectorAll('img');
                if (imgs.length === 0) return el.querySelector('canvas') !== null;
                return [...imgs].every(i => i.complete && i.naturalWidth > 0);
            }""",
            arg=PAGE_SELECTOR,
            timeout=15000,
        )
    except PWTimeout:
        pass  # fall back to the fixed waits below

    saved = 0
    review = 0
    i = 0
    idle = 0
    while True:
        all_pages = page.locator(PAGE_SELECTOR)
        total = all_pages.count()

        if i >= total:                    # no more pages loaded right now
            idle += 1
            if idle > IDLE_PATIENCE:      # waited long enough -> Alain is done
                break
            page.wait_for_timeout(1200)   # maybe the next batch is loading
            continue

        loc = all_pages.nth(i)
        try:
            loc.scroll_into_view_if_needed()   # Alain scrolls, not you
            page.wait_for_timeout(1500)        # let the page render
            out = OUTPUT_DIR / f"{doc_id}_{doc_name}_p{i + 1}.png"
            loc.screenshot(path=str(out))

            why = ""
            if FILTER_PAGES:
                txt = ""
                try:
                    txt = loc.inner_text(timeout=2000).strip()
                except Exception:
                    pass
                why = looks_like_junk(txt, out)

            if why:
                out.replace(REVIEW_DIR / out.name)
                review += 1
                print(f"      page {i + 1} -> review/ ({why})")
            else:
                saved += 1
                print(f"      saved {out.name}")
        except Exception as e:
            print(f"      ! page {i + 1} failed: {e}")

        i += 1
        if pages_to_grab and i >= pages_to_grab:
            break

    return saved, review


def collect_document_links(page, url):
    """Alain opens the normal document page and gathers links to other documents."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)  # let the 'related documents' sections render

    return page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")


def find_new_links(page, url, seen, queued_ids):
    """Collect links from a page — keep only new AND on-topic ones."""
    hrefs = collect_document_links(page, url)
    return harvest_links(hrefs, seen, queued_ids)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    if not doc_id_from(START_URL):
        raise SystemExit(f"Alain couldn't find a document ID in: {START_URL}")

    if REQUIRED_KEYWORDS and not matches_filter(START_URL):
        print("note: your START_URL doesn't match your own keywords, "
              "but Alain visits it anyway because YOU chose it.")

    unlimited = (MAX_LINKS_TO_FOLLOW == 0)
    max_total = None if unlimited else 1 + MAX_LINKS_TO_FOLLOW

    queue = [START_URL]
    queued_ids = {doc_id_from(START_URL)}
    seen = set()
    processed = 0
    total_saved = 0
    total_review = 0
    started = time.time()

    with sync_playwright() as p:
        # Bundled Chromium by default; set ALAIN_BROWSER_CHANNEL=msedge to reuse your Edge
        browser = p.chromium.launch(headless=HEADLESS, channel=BROWSER_CHANNEL or None)
        context = browser.new_context(
            viewport={"width": 1100, "height": 1500},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # ---- search mode — stock the queue before anything else ----
        for query in SEARCH_QUERIES:
            try:
                queue.extend(search_scribd(page, query, seen, queued_ids))
            except Exception as e:
                print(f"   ! Alain's search for '{query}' failed: {e}")
            time.sleep(2 + random.uniform(0, 1))

        print(f"\nAlain's queue is stocked: {len(queue)} document(s) to check")

        try:
            while queue and (max_total is None or processed < max_total):
                if TIME_CAP_MINUTES and (time.time() - started) >= TIME_CAP_MINUTES * 60:
                    print(f"\n[time cap] {TIME_CAP_MINUTES:g} minute(s) reached — "
                          f"Alain packs up. Everything captured so far is safe.")
                    break
                url = queue.pop(0)
                doc_id = doc_id_from(url)
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                doc_name = title_from_url(url)

                # ---- resume — skip what's already captured ----
                if already_captured(doc_id):
                    print(f"\n[skip] '{doc_name}' is already captured — "
                          f"Alain checks its links and moves on")
                    try:
                        fresh, ignored = find_new_links(page, url, seen, queued_ids)
                        queue.extend(fresh)
                        note = f" ({ignored} junk/off-topic bounced)" if ignored else ""
                        print(f"   queued {len(fresh)} new document link(s) — "
                              f"{len(queue)} waiting{note}")
                    except Exception as e:
                        print(f"   ! Alain couldn't collect links: {e}")
                    time.sleep(2 + random.uniform(0, 1))
                    continue

                processed += 1
                label = f"[{processed}]" if unlimited else f"[{processed}/{max_total}]"
                print(f"\n{label} Alain is on: {url}")

                # 1) screenshot this document (v2: adverts go to review/)
                try:
                    n, rj = screenshot_document(page, doc_id, PAGES_PER_DOC, doc_name)
                    total_saved += n
                    total_review += rj
                    print(f"   -> {n} paper page(s) kept, {rj} junk page(s) -> review/")
                except Exception as e:
                    print(f"   ! Alain couldn't screenshot this document: {e}")

                # 2) find more documents to visit
                if max_total is None or processed < max_total:
                    try:
                        fresh, ignored = find_new_links(page, url, seen, queued_ids)
                        queue.extend(fresh)
                        note = f" ({ignored} junk/off-topic bounced)" if ignored else ""
                        print(f"   queued {len(fresh)} new document link(s) — "
                              f"{len(queue)} waiting{note}")
                    except Exception as e:
                        print(f"   ! Alain couldn't collect links: {e}")

                # polite pause, with a human-ish wobble so it isn't robotic
                pause = DELAY_SECONDS + random.uniform(0, JITTER_SECONDS)
                time.sleep(pause)

        except KeyboardInterrupt:
            print("\n\n[STOP] Stopped by you! Everything captured so far is safe.")
            print("       Rerun alain.py anytime — Alain picks up right where he left off.")
        finally:
            browser.close()

    print(f"\nAlain is done — {total_saved} paper page(s) kept this run")
    print(f"                 {total_review} advert/junk page(s) parked in '{REVIEW_DIR}/'")
    print("                 (nothing deleted — check review/ if something looks missing)")
    print(f"Paper pages live in '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()
