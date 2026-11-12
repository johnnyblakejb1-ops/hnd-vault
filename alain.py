"""
Alain v2.1 — The Scribd Paper Camera
───────────────────────────────────
New design (Blaise-style): YOU pick the paper, Alain shoots it.

  1. He opens Scribd in a visible browser window (a persistent
     profile — login once and it survives restarts).
  2. YOU search / browse / open any document (any specialty —
     you verify it's the right paper with your own eyes).
  3. Press ENTER here: Alain switches to the clean embed view,
     scrolls through the whole document page by page,
     screenshots every page, and binds them into ONE PDF
     saved in scribd_papers/. If the clean view is blocked by
     Scribd's login wall, he falls back to shooting the very
     page you were already viewing.
  4. Every page is also saved into screenshots/ as
     <docid>_<slug>_p<N>.png — exactly the naming Bea (the
     stitcher) expects — so capture.bat can push them and Bea
     makes the branded pink PDFs automatically.

Console commands:
    ENTER     shoot the document you're viewing in the browser
    goto URL  drive the browser from the console (search results,
              a doc link a friend sent you, anything)
    list      show PDFs captured so far
    q         finish (writes alain_manifest.json)

Setup:
    pip install playwright pymupdf
    python -m playwright install chromium

Run:
    python alain.py

Notes:
  • Optional: log into YOUR Scribd account inside Alain's window —
    docs your subscription can read, Alain can read.
  • He captures exactly what Scribd shows you: if a page is
    blurred/limited for non-logged-in visitors, it stays that way.
"""

import re
import json
import sys
import time
import shutil
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# keep the console happy on every Windows encoding (this was the crash!)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ═══════════ SETTINGS (edit these) ═══════════
START_URL = "https://www.scribd.com/"

OUTPUT_DIR = Path("scribd_papers")     # preview PDFs (stay on your PC)
SCREENSHOT_DIR = Path("screenshots")   # page PNGs for Bea (get pushed)
HEADLESS = False          # keep False — you need to SEE what you pick

PAGE_SELECTOR = ".outer_page"   # one document page in the viewer
PAGES_PER_DOC = 0        # 0 = every page | N = just the first N pages
IDLE_PATIENCE = 5        # 'no new pages loading?' checks before stopping
RENDER_WAIT = 1500       # ms to let each page render before shooting
KEEP_IMAGES = False      # True = also keep the per-page PNGs next to the PDF

DOC_URL_RE = re.compile(r"scribd\.com/(?:document|embeds)/(\d+)")
PROFILE_DIR = Path("alain_profile")   # your login survives restarts
# ═══════════════════════════════════════════

CAPTURED = []   # running log of PDFs made this session


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
    """hnd-2023-CSN-Past-questions <- /document/819844284/hnd-2023-CSN-Past-questions"""
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


def remember(name, path, source_url, pages):
    CAPTURED.append({
        "name": name,
        "pages": pages,
        "size_kb": round(path.stat().st_size / 1024),
        "source_url": source_url,
    })


# ─────────── shooting ───────────

def shoot_pages(page, doc_id, slug, fallback_url=None):
    """Screenshot every page. Prefer the clean embed view; if Scribd's
    login wall hijacks it, fall back to the document page itself.
    Every page lands in screenshots/<docid>_<slug>_p<N>.png (Bea-ready).
    Returns (list of PNG paths, ) or ([], ) on failure."""
    embed = f"https://www.scribd.com/embeds/{doc_id}/content?start_page=1"

    used_embed = False
    try:
        page.goto(embed, wait_until="domcontentloaded", timeout=60000)
        settle(page)
        if "auth.scribd.com" in page.url:            # bounced to login wall
            print("   [lock] clean view needs a login — falling back...")
            raise PermissionError("auth")
        used_embed = True
    except Exception as e:
        # clean view unavailable → shoot the page the user was
        # already viewing (they verified it renders with their eyes)
        if fallback_url:
            print(f"   [retry] clean view blocked ({type(e).__name__}) — "
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

    # wait for the viewer's first page to appear
    try:
        page.wait_for_selector(PAGE_SELECTOR, timeout=30000)
    except PWTimeout:
        print("   [lock] the document isn't rendering — it may need login.")
        print("      → log into YOUR Scribd account inside Alain's browser")
        print("        window, reopen the paper, then press ENTER again.")
        print("      (v2.1 keeps you logged in across runs from now on.)")
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

    pngs = []
    i = 0
    idle = 0
    while True:
        all_pages = page.locator(PAGE_SELECTOR)
        total = all_pages.count()

        if i >= total:                    # nothing new loaded right now
            idle += 1
            if idle > IDLE_PATIENCE:      # waited enough → done
                break
            page.wait_for_timeout(1200)   # maybe next batch is loading
            continue

        loc = all_pages.nth(i)
        try:
            loc.scroll_into_view_if_needed()
            page.wait_for_timeout(RENDER_WAIT)
            out = SCREENSHOT_DIR / f"{doc_id}_{slug}_p{i + 1}.png"
            loc.screenshot(path=str(out))
            pngs.append(out)
            print(f"   [shot] page {i + 1}")
        except Exception as e:
            print(f"   [!] page {i + 1} failed: {e}")

        i += 1
        if PAGES_PER_DOC and i >= PAGES_PER_DOC:
            break

    return pngs


def images_to_pdf(pngs, pdf_path):
    """Bind page screenshots into one PDF with PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None, ("PyMuPDF not installed (pip install pymupdf) — "
                      "PNGs kept instead of a PDF")

    out = fitz.open()
    for png in pngs:
        img = fitz.open(str(png))              # open image as a doc
        pdf_bytes = img.convert_to_pdf()       # image → 1-page PDF
        img_pdf = fitz.open("pdf", pdf_bytes)
        out.insert_pdf(img_pdf)                # append that page
        img_pdf.close()
        img.close()
    out.set_metadata({
        "title": pdf_path.stem.replace("-", " "),
        "producer": "Alain v2.1 — Scribd Paper Camera",
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
        print("   → In the BROWSER: search / browse and OPEN the paper")
        print("     (click through until you see the actual document),")
        print("     then come back and press ENTER.")
        return

    slug = title_slug(url)
    print(f"\n   Shooting document {doc_id} ({slug})")

    pngs = shoot_pages(page, doc_id, slug, fallback_url=url)
    if not pngs:
        return

    base = slug or f"scribd_{doc_id}"
    pdf_path = next_free(OUTPUT_DIR / f"{base}.pdf")
    result, err = images_to_pdf(pngs, pdf_path)

    if err:
        print(f"   [note] {err}")
        print(f"   [img] {len(pngs)} page image(s) kept in: {SCREENSHOT_DIR}")
        return

    size_kb = pdf_path.stat().st_size / 1024
    print(f"\n   [OK] {len(pngs)} page(s) → {pdf_path.name} "
          f"({size_kb / 1024:.1f}MB)")
    remember(pdf_path.name, pdf_path, url, len(pngs))

    if KEEP_IMAGES:
        keep_dir = OUTPUT_DIR / pdf_path.stem
        keep_dir.mkdir(parents=True, exist_ok=True)
        for n, png in enumerate(pngs, 1):
            shutil.copy(png, keep_dir / f"page_{n:03d}.png")
        print(f"   [img] page images also kept in: {keep_dir}")

    # back to the document page you were on, so browsing continues
    if not url.rstrip("/") == page.url.rstrip("/"):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            settle(page)
        except Exception:
            pass


# ─────────── misc commands ───────────

def show_saved():
    files = sorted(OUTPUT_DIR.glob("*.pdf"))
    npngs = len(list(SCREENSHOT_DIR.glob("*.png")))
    print(f"\n   {len(files)} PDF(s) in {OUTPUT_DIR}/ | "
          f"{npngs} page PNG(s) in {SCREENSHOT_DIR}/")
    for f in files:
        print(f"   - {f.name}  ({f.stat().st_size // 1024}KB)")


def main():
    print(r"""
    +=================================================+
    |   ALAIN v2.1 — THE SCRIBD PAPER CAMERA          |
    |   You pick the paper. He shoots every page.     |
    |   You see it first → he turns it into a PDF.    |
    +=================================================+
""")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # persistent profile: your Scribd login survives restarts
        # (folder 'alain_profile' next to this script)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=HEADLESS,
            viewport={"width": 1100, "height": 1500},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
        )
        page = context.pages[0] if context.pages else context.new_page()

        # site pop-ups — Alain closes them himself
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
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)

        print(
            "\nIN THE BROWSER WINDOW (that's Alain's browser):\n"
            "     * FIRST TIME: log into YOUR Scribd account — Alain now\n"
            "       REMEMBERS your login between runs (alain_profile folder).\n"
            "     * search e.g.  'cameroon HND accountancy past questions',\n"
            "     * open a paper, EYEBALL it — is it the right one?\n"
            "   Then press ENTER here and Alain shoots every page → 1 PDF.\n"
            "   Open the next paper, ENTER again. 'q' when you're done.")

        try:
            while True:
                try:
                    raw = input(f"\n[ENTER]=shoot this paper | goto URL | "
                                f"list | q=done\n>> ({page.url[:55]}) ").strip()
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
        except KeyboardInterrupt:
            print("\n[stop] stopped — everything captured so far is safe.")

        context.close()

    manifest_path = OUTPUT_DIR / "alain_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "site": START_URL,
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pdfs": CAPTURED,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 50}")
    print(f"Alain is done. {len(CAPTURED)} PDF(s) in {OUTPUT_DIR}/")
    print(f"Page PNGs for Bea are in {SCREENSHOT_DIR}/ — run capture.bat to push them.")
    print(f"manifest: {manifest_path}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
