"""The Internet Archive's own OCR of the book as per-page line files: the second reading.

It was made from the same 600 ppi scan by another program, so wherever it and
our reading (build/ocr/) differ on a line, one of the two is wrong.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from molitvenik_tools.fetch import FetchError, download, is_fetched, run_alone

STEP = "ia-ocr"
JOBS = 8
DJVU_URL = "https://archive.org/download/pravoslavni-molitvenik/Pravoslavni%20molitvenik_djvu.xml"
CYR = re.compile(r"[Ѐ-ӿ]")  # the Cyrillic block, U+0400–U+04FF


def page_lines(obj: ET.Element) -> list[str]:
    """Text of the lines of one page object that contain a Cyrillic letter, in order.

    A page number, ornament marks or a line read as Latin letters carries nothing
    that could be compared with our reading, so it is left out. The running title
    stays, as it does in the fixture files: the comparison lines the two readings
    up by their words, so a line more at the start marks nothing."""
    lines = []
    for line in obj.iter("LINE"):
        words = [(word.text or "").strip() for word in line.iter("WORD")]
        text = " ".join(word for word in words if word)
        if CYR.search(text):
            lines.append(text)
    return lines


def iter_objects(xml_path) -> Iterator[tuple[int, str]]:
    """(PDF page, XML text) of every page object of a DjVu XML file, in order.

    The file is read as a stream and every object is dropped once it has been
    handed out. The n-th object (from 0) is Archive leaf n, which is PDF page
    n + 1."""
    leaf = -1
    with open(xml_path, "rb") as fh:
        for _, obj in ET.iterparse(fh, events=("end",)):
            if obj.tag == "OBJECT":
                leaf += 1
                yield leaf + 1, ET.tostring(obj, encoding="unicode")
                obj.clear()


def object_lines(object_xml: str) -> list[str]:
    """The lines of one page object given as XML text: the unit the pool hands out."""
    return page_lines(ET.fromstring(object_xml))


def write_page(out_dir: Path, page: int, lines: list[str]) -> None:
    """The file of one page (contract C3): build/ia-ocr/p-NNN.json."""
    text = json.dumps({"page": page, "lines": lines}, ensure_ascii=False) + "\n"
    (out_dir / f"p-{page:03d}.json").write_text(text, encoding="utf-8")


def write_pages(xml_path, out_dir, jobs: int = JOBS) -> int:
    """Write one file per page object; returns the number of pages."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    objects = list(iter_objects(xml_path))
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        readings = pool.map(object_lines, (xml for _, xml in objects))
        for index, lines in enumerate(readings):
            write_page(out_dir, objects[index][0], lines)
    return len(objects)


def add_arguments(parser) -> None:
    """The options of the step, shared by `molitvenik ia-ocr` and the module run on its own."""
    parser.add_argument("--xml", type=Path, help="the DjVu XML file (default: downloaded to build/ia/)")
    parser.add_argument("--jobs", type=int, default=JOBS, help="pages written at once (default: 8)")


def add_parser(subparsers) -> None:
    """Register the step under `molitvenik`, as every step does (contract C8)."""
    add_arguments(subparsers.add_parser("ia-ocr", help="turn the Archive's own OCR into build/ia-ocr/"))


def run(args, root: Path) -> int:
    xml = Path(args.xml) if args.xml is not None else root / "build" / "ia" / "djvu.xml"
    if args.xml is None and not is_fetched(xml):
        try:
            download(DJVU_URL, xml)
        except FetchError as exc:
            print(exc, file=sys.stderr)
            return 1
    if not xml.is_file():
        print(f"{xml} is not a file", file=sys.stderr)
        return 1
    count = write_pages(xml, root / "build" / "ia-ocr", args.jobs)
    print(f"pages: {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_alone(STEP, add_arguments, run, argv)


if __name__ == "__main__":
    sys.exit(main())
