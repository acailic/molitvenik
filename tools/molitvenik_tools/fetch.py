"""Fetch the page images into build/pages/.

By default the 600 ppi scan of the same book on the Internet Archive is
downloaded; with --pdf the maintainer's 150 DPI PDF is rendered instead. The
step leaves in build/pages/SOURCE.txt which of the two it used, because the OCR
step reads the two kinds of page at different scales.
"""

import argparse
import http.client
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

ARCHIVE = "archive"  # what SOURCE.txt holds after a download
ARCHIVE_URL = "https://archive.org/download/pravoslavni-molitvenik/page"
FIRST_PAGE, LAST_PAGE = 8, 177  # PDF pages of the twelve prayer sections
PDF_DPI = 150  # the resolution the maintainer's PDF is scanned at
RETRIES = 3
RETRY_DELAY = 2.0  # seconds between two tries
TIMEOUT = 120  # seconds for one try


class FetchError(RuntimeError):
    """A file could not be fetched."""


def page_url(page: int) -> str:
    """Address of the Archive image of a PDF page; the Archive leaf is page − 1."""
    return f"{ARCHIVE_URL}/n{page - 1}_w2000.jpg"


def page_file(page: int) -> str:
    """Name of the downloaded Archive image of a page in build/pages/."""
    return f"n{page - 1:03d}_w2000.jpg"


def pdf_page_file(page: int) -> str:
    """Name of a page rendered from the PDF in build/pages/."""
    return f"p-{page:03d}.png"


def is_fetched(path: Path) -> bool:
    """True when the file is there and not empty."""
    return path.exists() and path.stat().st_size > 0


def http_get(url: str) -> bytes:
    """One try: the body of `url`."""
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return response.read()


def download(url: str, dest: Path) -> None:
    """Write the body of `url` to `dest`, trying again RETRIES times after a failed try.

    The body goes to `<dest>.part` first and is renamed once it is whole, so that
    an interrupted run never leaves a short file that a later run would take for
    a fetched one."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(RETRIES + 1):
        try:
            body = http_get(url)
            if not body:
                raise OSError("the response was empty")
        except (OSError, http.client.HTTPException) as exc:
            failure = exc
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
        else:
            part.write_bytes(body)
            part.replace(dest)
            return
    raise FetchError(f"could not download {url} after {RETRIES + 1} tries: {failure}") from failure


def download_page(page: int, pages_dir: Path) -> str:
    """Fetch the Archive image of one page; "skipped" when it is already there."""
    dest = pages_dir / page_file(page)
    if is_fetched(dest):
        return "skipped"
    download(page_url(page), dest)
    return "fetched"


def render_page(page: int, pages_dir: Path, pdf: Path) -> str:
    """Render one page of the PDF at 150 DPI with pdftoppm; "skipped" when it is already there."""
    dest = pages_dir / pdf_page_file(page)
    if is_fetched(dest):
        return "skipped"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(PDF_DPI),
            "-png",
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            str(pdf),
            str(dest.with_suffix("")),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "fetched"


def add_arguments(parser) -> None:
    """The options of the step, shared by `molitvenik fetch` and the module run on its own."""
    parser.add_argument("--first", type=int, default=FIRST_PAGE, help="first PDF page (default: 8)")
    parser.add_argument("--last", type=int, default=LAST_PAGE, help="last PDF page (default: 177)")
    parser.add_argument("--jobs", type=int, default=4, help="pages fetched at once (default: 4)")
    parser.add_argument("--pdf", type=Path, help="render this PDF instead of downloading the scan")


def add_parser(subparsers) -> None:
    """Register the step under `molitvenik`, as every step does (contract C8)."""
    add_arguments(subparsers.add_parser("fetch", help="download the page images into build/pages/"))


def run(args, root: Path) -> int:
    pages_dir = root / "build" / "pages"
    if args.first > args.last:
        print(f"--first {args.first} is after --last {args.last}", file=sys.stderr)
        return 1
    if args.pdf is None:
        work, source = download_page, ARCHIVE
    else:
        pdf = args.pdf.resolve()
        if shutil.which("pdftoppm") is None:
            print(
                "pdftoppm is not installed: it is needed to render a PDF (it is part of poppler)",
                file=sys.stderr,
            )
            return 1
        if not pdf.is_file():
            print(f"{pdf} is not a file", file=sys.stderr)
            return 1
        work, source = partial(render_page, pdf=pdf), str(pdf)
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages = range(args.first, args.last + 1)
    counts: Counter = Counter()
    failed = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {page: pool.submit(work, page, pages_dir) for page in pages}
        for page, future in futures.items():
            try:
                counts[future.result()] += 1
            except (FetchError, subprocess.CalledProcessError) as exc:
                failed.append(page)
                print(f"page {page}: {exc}", file=sys.stderr)
    print(
        f"{len(pages)} pages: fetched {counts['fetched']}, skipped {counts['skipped']}, failed {len(failed)}"
    )
    if failed:
        return 1
    (pages_dir / "SOURCE.txt").write_text(source + "\n", encoding="utf-8")
    return 0


def find_root() -> Path:
    """The repository root for a step run on its own: the nearest directory with a
    pyproject.toml, from the current one upwards, else the one this package sits in."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return Path(__file__).resolve().parents[2]


def run_alone(step: str, add_arguments, run, argv: list[str] | None = None) -> int:
    """Command-line entry of a step that is run on its own:
    `uv run python -m molitvenik_tools.fetch --first 8 --last 30`.

    It takes the options of the step and --root, in any order. (`molitvenik`
    itself is cli.py; this spares every step module a copy of the same lines.)"""
    parser = argparse.ArgumentParser(prog=f"python -m molitvenik_tools.{step}")
    parser.add_argument(
        "--root",
        type=Path,
        default=find_root(),
        help="repository root (default: the nearest directory with a pyproject.toml)",
    )
    add_arguments(parser)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    return run(args, args.root)


def main(argv: list[str] | None = None) -> int:
    return run_alone("fetch", add_arguments, run, argv)


if __name__ == "__main__":
    sys.exit(main())
