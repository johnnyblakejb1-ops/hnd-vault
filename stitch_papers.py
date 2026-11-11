"""
Bea — Alain's seamstress. Turns his screenshots into tidy, site-ready PDFs.
---------------------------------------------------------------------------
Group Alain's screenshots (named  <docid>_<title>_p<N>.png) into one PDF per
document, pages in the right order. Optionally lay every page on the cambook
slightly-pink paper with a branded cover (this is also how we handle blurred
pages — "copy it unto our pink paper").

Run (from the folder that contains screenshots/):
    python stitch_papers.py              # plain PDFs into PDFs/
    python stitch_papers.py --pink       # pages on the cambook pink paper + cover
    python stitch_papers.py --include-review   # also use pages parked in review/
    python stitch_papers.py --force      # rebuild PDFs that already exist

Already-stitched documents are skipped by default (safe for nightly reruns);
--force rebuilds every PDF from the screenshots on disk.

Requires: pip install pillow
"""

import argparse
import csv
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---- cambook brand ----
PINK_BG = (252, 229, 236)
DARK = (59, 10, 30)
ACC = (176, 66, 107)
GOLD = (176, 128, 32)

NAME_RE = re.compile(r"^(\d+)_(.+)_p(\d+)\.png$", re.IGNORECASE)
YEAR_RE = re.compile(r"(20\d{2})")


def load_font(bold=False, size=30):
    """Windows first (Alain's home), Linux fallback, then default."""
    cands = []
    if bold:
        cands.append("C:/Windows/Fonts/arialbd.ttf")
    cands += [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_lines(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_cover(slug):
    """Branded pink cover page (A4-ish at 150 dpi)."""
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), PINK_BG)
    d = ImageDraw.Draw(img)
    f_big = load_font(True, 84)
    f_mid = load_font(False, 38)
    f_small = load_font(False, 30)

    title = slug.replace("-", " ").upper()
    year = YEAR_RE.search(title)
    kicker = "CAMEROON  •  HND PAST QUESTIONS" + (f"  •  {year.group(1)}" if year else "")

    d.text((100, 240), kicker, font=f_mid, fill=ACC)
    y = 400
    for ln in wrap_lines(d, title, f_big, W - 200):
        d.text((100, y), ln, font=f_big, fill=DARK)
        y += 104
    d.rectangle([100, y + 40, W - 100, y + 54], fill=GOLD)
    d.text((100, y + 110), "Collected for the cambook vault", font=f_small, fill=DARK)
    d.text((100, y + 160), "read  •  revise  •  pass", font=f_small, fill=ACC)
    return img


def pink_page(img, idx, total):
    """Lay one scanned/rendered page onto our slightly pink brand paper."""
    M, TOP, BOT = 48, 64, 56
    canvas = Image.new("RGB", (img.width + 2 * M, img.height + TOP + BOT), PINK_BG)
    canvas.paste(img, (M, TOP))
    d = ImageDraw.Draw(canvas)
    d.text((M, 18), "cambook  •  hnd vault", font=load_font(False, 24), fill=ACC)
    foot = f"— {idx} / {total} —"
    fw = d.textlength(foot, font=load_font(False, 22))
    d.text(((canvas.width - fw) / 2, canvas.height - 42), foot,
           font=load_font(False, 22), fill=DARK)
    return canvas


def normalize_widths(imgs):
    """Make all pages share the width of page 1 (Scribd sizes can wobble)."""
    w0 = imgs[0].width
    fixed = []
    for im in imgs:
        if abs(im.width - w0) > 2:
            h = round(im.height * w0 / im.width)
            im = im.resize((w0, h))
        fixed.append(im)
    return fixed


def main():
    ap = argparse.ArgumentParser(description="Stitch Alain's screenshots into PDFs")
    ap.add_argument("--dir", default="screenshots", help="folder with the PNGs")
    ap.add_argument("--out", default="PDFs", help="output folder for PDFs")
    ap.add_argument("--pink", action="store_true",
                    help="lay every page on the cambook pink paper + branded cover")
    ap.add_argument("--dpi", type=float, default=150.0)
    ap.add_argument("--include-review", action="store_true",
                    help="also use pages Alain parked in screenshots/review/")
    ap.add_argument("--force", action="store_true",
                    help="rebuild PDFs that already exist (default: stitch only new docs)")
    args = ap.parse_args()

    src, out = Path(args.dir), Path(args.out)
    if not src.exists():
        raise SystemExit(f"No folder called '{src}' — run alain.py first.")
    out.mkdir(parents=True, exist_ok=True)

    groups = {}
    skipped_review = 0
    for f in sorted(src.rglob("*.png")):
        if not args.include_review and "review" in f.relative_to(src).parts:
            skipped_review += 1
            continue
        m = NAME_RE.match(f.name)
        if not m:
            continue
        groups.setdefault((m.group(1), m.group(2)), []).append((int(m.group(3)), f))

    if not groups:
        print(f"No screenshot pages matching <docid>_<title>_p<N>.png in '{src}'.\n"
              f"Bea idles — nothing stitched yet. (Alain hasn't captured anything.)")
        return

    rows = []
    for (doc_id, slug), items in sorted(groups.items()):
        items.sort(key=lambda t: t[0])
        pages = [Image.open(p).convert("RGB") for _, p in items]
        pages = normalize_widths(pages)

        if args.pink:
            n = len(pages)
            pages = [pink_page(im, i + 1, n) for i, im in enumerate(pages)]
            pages.insert(0, make_cover(slug))

        dest = out / f"{slug}.pdf"
        if dest.exists() and not args.force:
            print(f"  {dest.name}: already stitched — skipping (--force to rebuild)")
            rows.append([doc_id, slug, len(items), dest.name,
                         dest.stat().st_size // 1024])
            continue
        pages[0].save(dest, "PDF", save_all=True, append_images=pages[1:],
                      resolution=args.dpi)
        rows.append([doc_id, slug, len(items), dest.name, dest.stat().st_size // 1024])
        print(f"  {dest.name}: {len(items)} page(s), {dest.stat().st_size // 1024} KB")

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "slug", "pages", "pdf", "kb"])
        w.writerows(rows)

    print(f"\nBea is done — {len(rows)} paper(s) stitched into '{out}/'")
    if skipped_review:
        print(f"({skipped_review} review/ page(s) left out — rerun with --include-review to use them)")


if __name__ == "__main__":
    main()
