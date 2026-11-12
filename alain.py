"""
Alain v3 — the Scribd Paper Camera (you pick, he shoots)
=========================================================
1. Alain opens Scribd in a VISIBLE browser window (your Edge if you
   have it — no big downloads; otherwise bundled Chromium).
2. YOU search, browse, open the paper you want, and eyeball it.
3. Press ENTER in the console: Alain shoots every page of the clean
   embed view (falls back to the page you're viewing if Scribd walls it),
   judges every page (advert pages go to screenshots/review/ — nothing
   is ever deleted), names every keeper  <docid>_<slug>_p<N>.png  in
   screenshots/ — exactly the naming Bea (the stitcher) expects — and
   binds the keepers into a preview PDF in scribd_papers/.
4. Double-click capture.bat afterwards: screenshots go to GitHub,
   Bea stitches the branded pink-paper PDFs automatically.

Console commands:
    ENTER      shoot the document you're viewing right now
    goto URL   drive the browser somewhere else
    list       show what's captured so far
    q          finish (writes alain_manifest.json)

Setup (one time):
    pip install playwright pillow
    No browser download needed — Alain uses your Edge.
    (pymupdf is optional; only the local preview PDF needs it.)

Notes:
  * Optional: log into YOUR Scribd account inside Alain's window —
    the login is remembered in alain_profile/ and that folder NEVER
    leaves your PC (it is git-ignored).
  * He captures exactly what Scribd shows you: a page blurred for
    free visitors stays blurred.
"""

import json
import os
import re
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# never let a console encoding kill the run (Windows code pages!)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ═══════════ SETTINGS (edit these) ═══════════
START_URL = "https://www.scribd.com/"

OUTPUT_DIR = Path("screenshots")          # keeper pages (Bea reads this)
REVIEW_DIR = OUTPUT_DIR / "review"        # suspect pages (never deleted)
PDF_DIR = Path("scribd_papers")           # local preview PDFs (not uploaded)
PROFILE_DIR = Path("alain_profile")       # your Scribd login (not uploaded)

HEADLESS = os.environ.get("ALAIN_HEADLESS", "") != "1"   # pick mode: keep visible
BROWSER_CHANNEL = os.environ.get("ALAIN_BROWSER_CHANNEL", "")  # "", msedge, chrome

PAGE_SELECTOR = ".outer_page"     # one document page in the viewer
PAGES_PER_DOC = int(os.environ.get("ALAIN_PAGES_PER_DOC", "0"))  # 0 = every page
IDLE_PATIENCE = 5                 # 'no new pages loading?' checks before stopping
RENDER_WAIT = 1500                # ms to let each page render before shooting
KEEP_IMAGES = False               # True = also copy per-page PNGs next to the PDF

DOC_URL_RE = re.compile(r"scribd\.com/(?:document|embeds)/(\d+)")

# ---- page judge (from Alain v2 — machine checks what the eye might miss) ----
FILTER_PAGES = True               # advert-looking pages -> review/ even in a chosen doc
JUNK_PAGE_WORDS = [
    "university", "admission", "apply now", "apply here", "ielts", "scholarship",
    "tuition", "study abroad", "campus", "www.", "http", "whatsapp", "click here",
    "follow us", "subscribe", "sign up", "enrol", "brochure", "telegram",
    "facebook", "instagram", "tutorials", "register now", "hotline", "call now",
]
EXAM_PAGE_WORDS = [
    "question", "paper", "answer", "instruction", "marks", "section",
    "candidate", "examination", "diploma", "hnd", "semester", "time allowed",
    "duration", "ministry", "republic", "subject", "series",
]
# ═══════════════════════════════════════════

CAPTURED = []   # running log for alain_manifest.json


# ─────────── helpers ───────────

def settle(page):
    """Wait until a page has stopped navigating before touching it."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(700)


def doc_id_from(url):
    m = DOC_URL_RE.search(url or "")
    return m.group(1) if m else None


def title_slug(url):
    path = urllib.parse.urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    slug = re.sub(r"[^\w\-]", "-", slug).strip("-").lower()
    return slug[:70] or "paper"


def next_free(path):
    """scribd_papers/foo.pdf, foo_2.pdf, foo_3.pdf ..."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while (path.parent / f"{stem}_{n}{suffix}").exists():
        n += 1
    return path.parent / f"{stem}_{n}{suffix}"


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
    """Returns a reason string if the page smells like an advert, '' if keeper."""
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


# ─────────── the browser ───────────

def launch_browser(p):
    """Try, in order: (1) the default/bundled browser exactly like v2.1
    (proven to open on your PC — no 'channel' keyword used), (2) Edge,
    (3) Chrome. Returns (context, name)."""
    LAUNCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/126.0.0.0 Safari/537.36")
    last_err = None

    if not BROWSER_CHANNEL:
        # 1) v2.1-style launch — no channel keyword at all. Oldest & safest.
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=HEADLESS,
                viewport={"width": 1100, "height": 1500},
                user_agent=LAUNCH_UA,
            )
            print("   [browser] started (default browser)")
            return ctx, "bundled"
        except Exception as e:
            last_err = e
            print(f"   [browser] default launch failed "
                  f"({str(e).splitlines()[0][:80]})")

    # 2) and 3) Edge / Chrome via channel keyword (needs newer playwright)
    for ch, label in (("msedge", "Edge"), ("chrome", "Chrome")):
        if BROWSER_CHANNEL and ch != BROWSER_CHANNEL:
            continue
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=HEADLESS,
                channel=ch,
                viewport={"width": 1100, "height": 1500},
                user_agent=LAUNCH_UA,
            )
            print(f"   [browser] started {label}")
            return ctx, ch
        except Exception as e:
            last_err = e
            print(f"   [browser] {label} not available "
                  f"({str(e).splitlines()[0][:80]})")

    raise SystemExit(
        "\nAlain couldn't start any browser.\n"
        "Fix — install his bundled browser once:\n"
        "    python -m playwright install chromium\n"
        f"Last error was: {last_err}"
    )


# ─────────── shooting ───────────

def shoot_pages(page, doc_id, slug, fallback_url=None):
    """Screenshot every page. Prefer the clean embed view; if Scribd's
    login wall hijacks it, fall back to the document page itself.
    Keepers land in screenshots/ as <docid>_<slug>_p<N>.png (Bea-ready);
    suspect pages go to screenshots/review/. Returns list of keeper paths."""
    embed = f"https://www.scribd.com/embeds/{doc_id}/content?start_page=1"

    try:
        page.goto(embed, wait_until="domcontentloaded", timeout=60000)
        settle(page)
        if "auth.scribd.com" in page.url:            # bounced to login wall
            print("   [lock] clean view needs a login — falling back...")
            raise PermissionError("auth")
    except Exception as e:
        if fallback_url:
            print(f"   [fallback] clean view blocked ({type(e).__name__}) — "
                  f"shooting the page you were viewing instead")
            try:
                page.goto(fallback_url, wait_until="domcontentloaded",
                          timeout=60000)
                settle(page)
            except Exception as e2:
                print(f"   [!] couldn't return to the document page: {e2}")
                return []
        else:
            print(f"   [!] clean view blocked and no fallback URL: {e}")
            return []

    try:
        page.wait_for_selector(PAGE_SELECTOR, timeout=30000)
    except PWTimeout:
        print("   [lock] the document isn't rendering — it may need login.")
        print("          -> log into YOUR Scribd account inside Alain's browser")
        print("             window, reopen the paper, then press ENTER again.")
        return []

    # wait for page 1's content to actually finish loading
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
        pass  # fixed waits below are the fallback

    keepers = []
    i = 0
    idle = 0
    while True:
        all_pages = page.locator(PAGE_SELECTOR)
        total = all_pages.count()

        if i >= total:                    # nothing new loaded right now
            idle += 1
            if idle > IDLE_PATIENCE:      # waited enough -> done
                break
            page.wait_for_timeout(1200)   # maybe next batch is loading
            continue

        loc = all_pages.nth(i)
        try:
            loc.scroll_into_view_if_needed()
            page.wait_for_timeout(RENDER_WAIT)
            out = OUTPUT_DIR / f"{doc_id}_{slug}_p{i + 1}.png"
            loc.screenshot(path=str(out))
            print(f"   [shot] page {i + 1}")

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
                print(f"   [review] page {i + 1} ({why})")
            else:
                keepers.append(out)
        except Exception as e:
            print(f"   [!] page {i + 1} failed: {e}")

        i += 1
        if PAGES_PER_DOC and i >= PAGES_PER_DOC:
            break

    return keepers


def images_to_pdf(pngs, pdf_path):
    """Bind keeper pages into one preview PDF with PyMuPDF (optional)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None, "PyMuPDF not installed (pip install pymupdf) — preview PDF skipped, PNGs are safe"

    out = fitz.open()
    for png in pngs:
        img = fitz.open(str(png))
        pdf_bytes = img.convert_to_pdf()
        img_pdf = fitz.open("pdf", pdf_bytes)
        out.insert_pdf(img_pdf)
        img_pdf.close()
        img.close()
    out.set_metadata({
        "title": pdf_path.stem.replace("-", " "),
        "producer": "Alain v3 — Scribd Paper Camera",
    })
    out.save(str(pdf_path), garbage=3, deflate=True)
    out.close()
    return pdf_path, None


# ─────────── the main action: ENTER ───────────

def shoot_current(page):
    """Shoot whatever document the browser is showing right now."""
    settle(page)
    url = page.url
    doc_id = doc_id_from(url)

    if not doc_id:
        print(f"\n   You're on: {url[:70]}")
        print("   This isn't a Scribd document page yet.")
        print("   -> In the BROWSER: search / browse and OPEN the paper")
        print("     (click through until you see the actual document),")
        print("     then come back and press ENTER.")
        return

    slug = title_slug(url)
    print(f"\n   Shooting document {doc_id} ({slug})")

    keepers = shoot_pages(page, doc_id, slug, fallback_url=url)
    if not keepers:
        print("   [!] nothing kept this time.")
        return

    base = slug or f"scribd_{doc_id}"
    pdf_path = next_free(PDF_DIR / f"{base}.pdf")
    result, err = images_to_pdf(keepers, pdf_path)

    print(f"\n   [OK] {len(keepers)} page(s) kept in screenshots/")
    if err:
        print(f"   [note] {err}")
    else:
        size_mb = pdf_path.stat().st_size / 1024 / 1024
        print(f"   [OK] preview PDF: {pdf_path.name} ({size_mb:.1f}MB)")
    CAPTURED.append({
        "name": f"{base} ({len(keepers)}p)",
        "pages": len(keepers),
        "source_url": url,
    })

    if KEEP_IMAGES:
        keep_dir = PDF_DIR / pdf_path.stem
        keep_dir.mkdir(parents=True, exist_ok=True)
        for n, png in enumerate(keepers, 1):
            shutil.copy(png, keep_dir / f"page_{n:03d}.png")

    # back to the document page you were on, so browsing continues
    if not url.rstrip("/") == page.url.rstrip("/"):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            settle(page)
        except Exception:
            pass


# ─────────── misc commands ───────────

def show_saved():
    pngs = [p for p in OUTPUT_DIR.glob("*.png")]
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"\n   [list] {len(pngs)} page PNG(s) in {OUTPUT_DIR}/ "
          f"| {len(pdfs)} preview PDF(s) in {PDF_DIR}/")
    for f in pdfs:
        print(f"     - {f.name}  ({f.stat().st_size // 1024}KB)")


def write_manifest():
    manifest_path = OUTPUT_DIR / "alain_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "site": START_URL,
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "captures": CAPTURED,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n{'=' * 50}")
    print(f"Alain is done. {len(CAPTURED)} capture(s) this session.")
    print(f"Keepers live in {OUTPUT_DIR}/  -> run capture.bat to push them.")
    print(f"Manifest: {manifest_path}")
    print(f"{'=' * 50}")


def main():
    print(r"""
    +=================================================+
    |   ALAIN v3 — THE SCRIBD PAPER CAMERA            |
    |   You pick the paper. He shoots every page.     |
    |   You see it first -> he turns it into a PDF.   |
    +=================================================+
""")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            context, _ = launch_browser(p)
            page = context.pages[0] if context.pages else context.new_page()

            def on_dialog(dialog):
                try:
                    print(f"   [pop-up] {(dialog.message or '')[:60]!r} — closed")
                except Exception:
                    pass
                try:
                    dialog.accept()
                except Exception:
                    try:
                        dialog.dismiss()
                    except Exception:
                        pass
            page.on("dialog", on_dialog)

            print(f"Opening {START_URL}")
            try:
                page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"   [!] opening failed: {e}")

            print(
                "\nIN THE BROWSER WINDOW (that's Alain's browser):\n"
                "  * FIRST TIME: log into YOUR Scribd account — Alain\n"
                "    REMEMBERS your login between runs (alain_profile/).\n"
                "  * search e.g. 'cameroon HND accountancy past questions',\n"
                "  * open a paper, EYEBALL it — is it the right one?\n"
                "Then press ENTER here and Alain shoots every page.\n"
                "Open the next paper, ENTER again. 'q' when you're done.")

            while True:
                try:
                    raw = input(
                        f"\n[ENTER]=shoot this paper | goto URL | list | q=done\n"
                        f">> ({page.url[:55]}) ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                cmd = raw.lower()

                if cmd in ("q", "quit", "exit"):
                    break

                if cmd.startswith("goto") and len(raw.split()) > 1:
                    url = raw.split(None, 1)[1].strip()
                    if not url.startswith("http"):
                        url = START_URL.rstrip("/") + "/" + url.lstrip("/")
                    try:
                        page.goto(url, wait_until="domcontentloaded",
                                  timeout=60000)
                        settle(page)
                        print(f"   now on: {page.url[:70]}")
                    except Exception as e:
                        print(f"   [!] {e}")

                elif cmd == "list":
                    show_saved()

                elif cmd == "":
                    shoot_current(page)

                else:
                    print("   ? commands: ENTER (shoot) | goto URL | list | q")

            context.close()

    except KeyboardInterrupt:
        print("\n[stop] Ctrl+C — everything captured so far is safe.")

    write_manifest()


if __name__ == "__main__":
    main()
