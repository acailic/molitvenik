"""OCR of the page images: lines and words with boxes, confidence, colour and flags.

Tesseract reads every page three times: the base reading at half resolution, a
second at 40 % of it and a third in page segmentation mode 6. The later steps
work on the base reading; the other two only mark the words they read
differently, which is how a wrong word is found before anyone looks at the page.
"""

import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from molitvenik_tools import images
from molitvenik_tools.fetch import ARCHIVE, FIRST_PAGE, LAST_PAGE, page_file, pdf_page_file, run_alone

STEP = "ocr"
LANG = "srp"  # the Serbian model
MODEL = "srp.traineddata"
TESS_CONFIG = ("-c", "tessedit_load_sublangs=", "-c", "tessedit_create_tsv=1")
BASE_SCALE = 0.5  # half of the 600 ppi scan is about 300 ppi: the best reading (spec, section 5)
SMALL_SCALE = 0.4  # the second reading, 40 %
PDF_SCALE = 2.0  # the maintainer's PDF is scanned at 150 DPI and is upscaled instead
HEADER_SHARE = 0.09  # a line whose centre is in the top 9 % of the page is the running title
FOOTER_SHARE = 0.90  # a short line with a number in the bottom 10 % is the page number
LOW_CONF = 85.0  # Tesseract's confidence below this makes a word suspect
RED_SHARE = 0.5  # a word is red when at least half of its ink is
WORD_KEYS = ("text", "left", "top", "width", "height", "conf", "red", "color", "flags")
CYR = re.compile(r"[Ѐ-ӿ]")  # the Cyrillic block, U+0400–U+04FF
LAT = re.compile(r"[A-Za-z]")


def parse_tsv(path) -> list[dict]:
    """The words of the TSV that Tesseract wrote, in reading order.

    Only the rows of level 5 hold a word; the levels above them are the page,
    the block, the paragraph and the line. The rows are split at their tabs and
    not read as CSV: Tesseract prints a quote that it read as part of a word
    without quoting the field, and a CSV reader takes such a quote for the
    start of a field that ends many rows later, which silently dropped most of
    the lower half of three pages of the book."""
    words = []
    with open(path, encoding="utf-8") as fh:
        for row in fh:
            fields = row.rstrip("\r\n").split("\t")
            if len(fields) >= 12 and fields[0] == "5" and fields[11].strip():
                words.append(
                    {
                        "text": "\t".join(fields[11:]).strip(),
                        "left": int(fields[6]),
                        "top": int(fields[7]),
                        "width": int(fields[8]),
                        "height": int(fields[9]),
                        "conf": float(fields[10]),
                        "block": int(fields[2]),
                        "par": int(fields[3]),
                        "line": int(fields[4]),
                    }
                )
    return words


def run_tesseract(image_path, out_base, psm: int, tessdata=None) -> list[dict]:
    """Read one image with Tesseract and return its words.

    Tesseract writes a TSV and a TXT next to `out_base`; both are deleted once
    the TSV is read. The model's Serbian Latin sub-language is switched off: the
    `srp` model cannot print a Latin letter itself, but Tesseract retries a
    doubtful word with that model, which was the source of every Latin letter."""
    command = ["tesseract", str(image_path), str(out_base), "-l", LANG, "--psm", str(psm), *TESS_CONFIG]
    if tessdata is not None:
        command += ["--tessdata-dir", str(tessdata)]
    # one thread a page: eight pages at once would otherwise fight for the same cores
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    words = parse_tsv(f"{out_base}.tsv")
    Path(f"{out_base}.tsv").unlink(missing_ok=True)
    Path(f"{out_base}.txt").unlink(missing_ok=True)
    return words


def resolve_tessdata(tessdata) -> str | None:
    """The directory to give Tesseract for its model, or None for Tesseract's own path.

    A given directory is used when it holds srp.traineddata. Tesseract does not
    look any further than the directory it is given, so without the model there
    the default path is the only one that can work."""
    if tessdata is None or not (Path(tessdata) / MODEL).is_file():
        return None
    return str(tessdata)


def disagreements(base: list[dict], other: list[dict]) -> set[int]:
    """Indexes of the base words that another reading of the page disagrees about.

    Only small differences count: at most two words on either side. A longer run
    of differing words means that the two readings cut or ordered the passage
    differently, which says nothing about any single word. When the other reading
    has extra words, the word before them is suspected, for the readings are
    likely to have split it differently."""
    a = [w["text"].strip().lower() for w in base]
    b = [w["text"].strip().lower() for w in other]
    out = set()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or i2 - i1 > 2 or j2 - j1 > 2:
            continue
        if i1 < i2:
            out.update(range(i1, i2))
        elif i1 > 0:
            out.add(i1 - 1)
    return out


def word_flags(text: str, conf: float) -> list[str]:
    """What a word looks like, before the other readings are compared with it."""
    flags = []
    if conf < LOW_CONF:
        flags.append("low-confidence")
    if LAT.search(text):
        flags.append("latin-letters")
    if any(ch.isupper() for ch in text[1:]):
        flags.append("has-inner-caps")
    return flags


def color_of(red: float) -> str:
    return "red" if red >= RED_SHARE else "black"


def measure(words: list[dict]) -> dict:
    """A line of words with the median of their heights and of their centres."""
    return {
        "words": words,
        "h": statistics.median(w["height"] for w in words),
        "cy": statistics.median(w["top"] + w["height"] / 2 for w in words),
    }


def group_lines(words: list[dict]) -> list[dict]:
    """Tesseract's lines from the top of the page down, neighbours that share a
    visual line merged into one and the words of every line sorted by `left`.

    Neighbours are merged when their centres lie within half the smaller of
    their median heights (a centred red label followed by black text on the same
    row is often cut into two lines). Medians are used because a single tall box
    must not pull a line towards its neighbour. Only two neighbouring lines are
    compared: a grouping built from coordinates alone was tried and interleaved
    the words of two neighbouring lines on dense pages."""
    by_id: dict = {}
    for word in words:
        by_id.setdefault((word["block"], word["par"], word["line"]), []).append(word)
    lines = []
    for group in by_id.values():
        group.sort(key=lambda w: w["left"])
        lines.append(measure(group))
    lines.sort(key=lambda line: line["cy"])
    merged = []
    for line in lines:
        if merged and abs(line["cy"] - merged[-1]["cy"]) <= 0.5 * min(line["h"], merged[-1]["h"]):
            merged[-1] = measure(sorted(merged[-1]["words"] + line["words"], key=lambda w: w["left"]))
        else:
            merged.append(line)
    return merged


def classify_line(line: dict, height: int) -> str:
    """Kind of a line by its place on the page and by what it holds (contract C2)."""
    texts = [w["text"] for w in line["words"]]
    if line["cy"] < HEADER_SHARE * height:
        return "header"
    numbered = (
        len(texts) <= 3
        and any(re.fullmatch(r"\d{1,3}", text) for text in texts)
        and not any(len(CYR.findall(text)) >= 3 for text in texts)
    )
    if line["cy"] > FOOTER_SHARE * height and numbered:
        return "footer"
    if not any(CYR.search(text) for text in texts):
        return "ornament"
    return "content"


def make_line(line: dict, height: int) -> dict:
    """A grouped line as the page file holds it: its kind, its box, its text and its words."""
    words = line["words"]
    return {
        "kind": classify_line(line, height),
        "cy": round(line["cy"], 1),
        "top": min(w["top"] for w in words),
        "bottom": max(w["top"] + w["height"] for w in words),
        "left": min(w["left"] for w in words),
        "right": max(w["left"] + w["width"] for w in words),
        "text": " ".join(w["text"] for w in words),
        "words": [{key: w[key] for key in WORD_KEYS} for w in words],
    }


def save_greyscale(rgb: np.ndarray, path) -> None:
    """Write an RGB array as the 8-bit greyscale image that Tesseract reads."""
    with Image.fromarray(images.to_greyscale(rgb).astype(np.uint8), "L") as grey:
        grey.save(path)


def read_page(
    page: int,
    image_path,
    second_image_path,
    tessdata,
    *,
    scale: float = BASE_SCALE,
    small_scale: float | None = SMALL_SCALE,
) -> dict:
    """Read one page image into a page file (contract C2).

    `second_image_path` receives the page at the base scale: the boxes of the
    file are pixels of that image (build/review/img/p-NNN.png). A page of the
    maintainer's PDF is read with scale=PDF_SCALE and small_scale=None: at 150
    DPI there are no pixels to spare for a second scale, so the second reading
    is the one in mode 6 only."""
    source = images.load_rgb(image_path)
    rgb = images.resize(source, scale)
    height, width = rgb.shape[:2]
    Path(second_image_path).parent.mkdir(parents=True, exist_ok=True)
    with Image.fromarray(rgb, "RGB") as half:
        half.save(second_image_path)

    with tempfile.TemporaryDirectory(prefix="molitvenik-ocr-") as tmp:
        work = Path(tmp)
        save_greyscale(rgb, work / "base.png")
        base = run_tesseract(work / "base.png", work / "base", 3, tessdata)
        others = [("psm6", run_tesseract(work / "base.png", work / "psm6", 6, tessdata))]
        if small_scale is not None:
            save_greyscale(images.resize(source, small_scale), work / "small.png")
            others.insert(0, ("scale40", run_tesseract(work / "small.png", work / "small", 3, tessdata)))

    for word in base:
        share = images.red_share(word, rgb)
        word["red"] = round(share, 2)
        word["color"] = color_of(share)
        word["flags"] = word_flags(word["text"], word["conf"])
    for name, other in others:
        for index in disagreements(base, other):
            base[index]["flags"].append(f"differs:{name}")

    return {
        "page": page,
        "book_page": page + 3,
        "width": width,
        "height": height,
        "source_width": source.shape[1],
        "source_height": source.shape[0],
        "lines": [make_line(line, height) for line in group_lines(base)],
    }


def add_arguments(parser) -> None:
    """The options of the step, shared by `molitvenik ocr` and the module run on its own."""
    parser.add_argument("--first", type=int, default=FIRST_PAGE, help="first PDF page (default: 8)")
    parser.add_argument("--last", type=int, default=LAST_PAGE, help="last PDF page (default: 177)")
    parser.add_argument("--jobs", type=int, default=8, help="pages read at once (default: 8)")
    parser.add_argument("--tessdata", type=Path, help=f"directory with {MODEL} (default: Tesseract's own)")


def add_parser(subparsers) -> None:
    """Register the step under `molitvenik`, as every step does (contract C8)."""
    add_arguments(subparsers.add_parser("ocr", help="read the page images with Tesseract into build/ocr/"))


def run(args, root: Path) -> int:
    pages_dir = root / "build" / "pages"
    if args.first > args.last:
        print(f"--first {args.first} is after --last {args.last}", file=sys.stderr)
        return 1
    try:
        source = (pages_dir / "SOURCE.txt").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print("build/pages/SOURCE.txt is missing: run `molitvenik fetch` first", file=sys.stderr)
        return 1
    if shutil.which("tesseract") is None:
        print("tesseract is not installed: it is needed to read the pages", file=sys.stderr)
        return 1
    if source == ARCHIVE:
        scale, small_scale, name_of = BASE_SCALE, SMALL_SCALE, page_file
    else:
        scale, small_scale, name_of = PDF_SCALE, None, pdf_page_file
    page_images = {page: pages_dir / name_of(page) for page in range(args.first, args.last + 1)}
    missing = [str(page) for page, path in page_images.items() if not path.is_file()]
    if missing:
        print(
            f"no page image in build/pages for PDF page(s) {', '.join(missing)}: run `molitvenik fetch`",
            file=sys.stderr,
        )
        return 1
    tessdata = resolve_tessdata(args.tessdata)
    if args.tessdata is not None and tessdata is None:
        print(f"no {MODEL} in {args.tessdata}: Tesseract's own directory is used", file=sys.stderr)

    counts: Counter = Counter()
    failed = []
    words = flagged = 0
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {
            page: pool.submit(
                read_page,
                page,
                path,
                root / "build" / "review" / "img" / f"p-{page:03d}.png",
                tessdata,
                scale=scale,
                small_scale=small_scale,
            )
            for page, path in page_images.items()
        }
        for page, future in futures.items():
            try:
                data = future.result()
            except subprocess.CalledProcessError as exc:
                failed.append(page)
                print(f"page {page}: Tesseract failed: {(exc.stderr or '').strip()}", file=sys.stderr)
                continue
            out = root / "build" / "ocr" / f"p-{page:03d}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            counts.update(line["kind"] for line in data["lines"])
            for line in data["lines"]:
                if line["kind"] == "content":
                    words += len(line["words"])
                    flagged += sum(1 for w in line["words"] if w["flags"])
    print(
        f"pages={len(page_images)} lines={dict(counts)} words={words} flagged_words={flagged}"
        + (f" failed_pages={failed}" if failed else "")
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    return run_alone(STEP, add_arguments, run, argv)


if __name__ == "__main__":
    sys.exit(main())
