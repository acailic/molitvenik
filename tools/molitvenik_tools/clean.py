"""Turn OCR pages into the cleaned text of the book.

The pages come from the OCR step, after the proofreading corrections were
applied. This module joins the lines into paragraphs, resolves the hyphens of
words broken at a line end (also over a page break), removes the artefacts of
justified setting, tells red lines from black text, and sets aside the running
title, the page number, ornament lines and the footnote.

The output has the shape of contract C5: blocks in reading order, each a
``paragraph`` with coloured runs or a ``rubric`` (a red instruction or heading).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import tomllib

from molitvenik_tools.overrides import OverrideError, apply_overrides

INDENT_MIN = 45  # half-resolution pixels right of the margin that start a paragraph
DEFAULT_INDENT = 90  # the indent of a first line when the book gives no sample
DEFAULT_WIDTH = 730  # the width of the text block when the book gives no sample
WIDTH_TOLERANCE = 60  # how far a candidate edge may miss the width of the text block
MARGIN_TOLERANCE = 12  # first words this close together start at the same edge
CENTRED_TOLERANCE = 60  # a line with equally wide gaps on both sides is centred
ORNAMENT_GAP = 2.5  # a line this many line pitches below the text …
ORNAMENT_MAX_LETTERS = 2  # … with at most this many letters …
ORNAMENT_MAX_TOKENS = 3  # … in at most this many words …
ORNAMENT_LOWEST = 0.5  # … in the lower half of the page is an ornament, not text
ARTEFACT_CHARS = "·~|=—–_•¬#"  # spacing symbols of justified setting

ARTEFACT = re.compile(rf"[{re.escape(ARTEFACT_CHARS)}]+")
LETTER_OR_DIGIT = re.compile(r"\w", re.UNICODE)
LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def strip_artefacts(token: str) -> list[str]:
    """The token split into words, without its spacing symbols.

    A token that never had an artefact character is kept as it is, even when it
    is only punctuation: a bracket set apart by a wide space is real. A token
    made only of artefacts and punctuation vanishes.
    """
    if not ARTEFACT.search(token):
        return [token]
    rest = ARTEFACT.sub(" ", token).split()
    return rest if any(LETTER_OR_DIGIT.search(part) for part in rest) else []


def is_artefact(token: str) -> bool:
    """A token that is only a spacing symbol, which the justified setting produces."""
    return not strip_artefacts(token)


def line_words(line: dict) -> list[dict]:
    """The words of a line without the spacing artefacts; a word that contained one is split."""
    words = []
    for word in line["words"]:
        for text in strip_artefacts(word["text"]):
            words.append({**word, "text": text})
    return words


def first_word(line: dict) -> dict | None:
    """The first word of a line that is not a spacing artefact."""
    words = line_words(line)
    return words[0] if words else None


def join_hyphen(left: str, right: str) -> tuple[str, bool]:
    """Join the two halves of a word broken at a line end (``left`` ends with a hyphen).

    Returns the joined word and whether the hyphen was kept: it is removed when
    the second half continues with a lowercase letter, and kept when a capital
    letter follows, because then it may be a real hyphen of a compound.
    """
    if right[:1].islower():
        return left[:-1] + right, False
    return left + right, True


def line_pitch(lines: list[dict]) -> float:
    """The usual distance between two neighbouring lines of a page."""
    gaps = [b["cy"] - a["cy"] for a, b in zip(lines, lines[1:], strict=False) if 20 < b["cy"] - a["cy"] < 80]
    return statistics.median(gaps) if gaps else 0.0


def looks_like_ornament(words: list[dict], gap: float, height_share: float) -> bool:
    """Almost no letters, far below the text, low on the page: an ornament the OCR read as a word."""
    letters = sum(len(LETTER.findall(w["text"])) for w in words)
    return (
        gap >= ORNAMENT_GAP
        and len(words) <= ORNAMENT_MAX_TOKENS
        and letters <= ORNAMENT_MAX_LETTERS
        and height_share > ORNAMENT_LOWEST
    )


def line_starts(content: list[dict]) -> list[dict]:
    """The first word of every line, red or black."""
    return [first for line in content if (first := first_word(line)) is not None]


def edge_groups(starts: list[dict]) -> list[tuple[float, int]]:
    """The left edges where the given first words start, each with its number of lines."""
    groups: list[list] = []
    for word in sorted(starts, key=lambda item: item["left"]):
        if groups and word["left"] - groups[-1][0] <= MARGIN_TOLERANCE:
            groups[-1][1] += 1
        else:
            groups.append([word["left"], 1])
    return [(group[0], group[1]) for group in groups]


def page_edges(pages: list[dict]) -> tuple[dict[int, float], set[int]]:
    """The left edge of the text block of every page, and the pages whose edge is a guess.

    The edge is in half-resolution pixels. The first words of a page's lines
    start at a few left edges: the edge of the text block, where continuation
    lines begin, and further right, where paragraphs, centred headings and their
    lines begin. The text block has the same width on every page, so the edge
    of the block is the one that lines up with the right side of the page: a
    phantom word to the left of a line, or a lone continuation line, cannot
    fool that. When no edge lines up, the page has no full line at all: its
    lines are one-line prayers, the edge is one indent left of the leftmost,
    and the page is reported as a guess.
    """
    measured: dict[int, tuple[float, list[tuple[float, int]]]] = {}
    for page in pages:
        content = [line for line in page["lines"] if line["kind"] == "content" and line["words"]]
        starts = line_starts(content)
        if not starts:
            continue
        measured[page["page"]] = (max(line["right"] for line in content), edge_groups(starts))
    if not measured:
        return {}, set()

    def block_width(left_of: dict[int, float]) -> list[int]:
        return [
            round(right - left_of[number]) for number, (right, _) in measured.items() if number in left_of
        ]

    def common_width(widths: list[int]) -> float:
        """The median of the most frequent group of widths, rounded to 20 pixels.

        Most pages are ordinary: their leftmost edge is the edge of the block.
        Pages with short lines only, or with a phantom word, give a width that
        is far from the rest and must not pull the estimate away.
        """
        buckets: dict[int, list[int]] = {}
        for value in widths:
            buckets.setdefault(round(value / 20), []).append(value)
        return statistics.median(max(buckets.values(), key=len))

    # A first estimate of the width of the block, from the leftmost edge of every page.
    width = common_width(block_width({n: g[0][0] for n, (_, g) in measured.items()}))
    # The edge of each page: the group that lines up with the right side; the larger group wins a tie.
    chosen: dict[int, tuple[float, float]] = {}
    for number, (right, groups) in measured.items():
        score, _, left = min((abs(right - left - width), -count, left) for left, count in groups)
        chosen[number] = (score, left)
    fitting = [n for n, (score, _) in chosen.items() if score <= WIDTH_TOLERANCE]
    if fitting:
        width = statistics.median(block_width({n: chosen[n][1] for n in fitting}))
        for number, (right, groups) in measured.items():
            score, _, left = min((abs(right - left - width), -count, left) for left, count in groups)
            chosen[number] = (score, left)
    indents = [
        left - chosen[number][1]
        for number, (_, groups) in measured.items()
        if chosen[number][0] <= WIDTH_TOLERANCE
        for left, _ in groups
        if left - chosen[number][1] >= INDENT_MIN
    ]
    indent = statistics.median(indents) if indents else DEFAULT_INDENT

    margins: dict[int, float] = {}
    uncertain: set[int] = set()
    for number, (_, groups) in measured.items():
        score, left = chosen[number]
        if score <= WIDTH_TOLERANCE:
            margins[number] = left
        else:
            margins[number] = groups[0][0] - indent
            uncertain.add(number)
    return margins, uncertain


def page_margins(pages: list[dict]) -> dict[int, float]:
    """The left edge of the text block of every page, in half-resolution pixels."""
    return page_edges(pages)[0]


def clean_book(pages: list[dict], footnotes: list[dict]) -> dict:
    """Cleaned text of the book (contract C5) from OCR pages in reading order."""
    blocks: list[dict] = []
    notes: list[dict] = []
    kept_hyphens: list[dict] = []
    warnings: list[str] = []
    specs = {(int(f["page"]), f["starts_with"]) for f in footnotes}
    margins, uncertain = page_edges(pages)
    paragraph: dict | None = None

    def close() -> None:
        nonlocal paragraph
        if paragraph is None:
            return
        runs = paragraph["runs"]
        # A hyphen at the end of a paragraph is the artefact of a line break. It is
        # removed and reported, because it is also what a wrongly seen paragraph
        # start would look like.
        last = runs[-1]["parts"]
        if last[-1].endswith("-"):
            warnings.append(
                f"hyphen: page {paragraph['page_end']}: removed a hyphen at the end of a paragraph: "
                f"{last[-1]!r}"
            )
            last[-1] = last[-1][:-1]
        block = {
            "kind": paragraph["kind"],
            "page_start": paragraph["page_start"],
            "page_end": paragraph["page_end"],
        }
        if paragraph["kind"] == "rubric":
            block["text"] = " ".join(part for run in runs for part in run["parts"])
        else:
            block["runs"] = [
                {"text": " ".join(run["parts"]), "rubric": run["rubric"]} for run in runs if run["parts"]
            ]
        blocks.append(block)
        paragraph = None

    def feed(tokens: list[tuple[str, bool]], number: int) -> None:
        """Append the words of one line to the paragraph being filled."""
        assert paragraph is not None
        at_line_start = True
        for text, red in tokens:
            runs = paragraph["runs"]
            if runs and at_line_start and runs[-1]["parts"][-1].endswith("-"):
                previous = runs[-1]["parts"][-1]
                runs[-1]["parts"][-1], kept = join_hyphen(previous, text)
                if kept:
                    kept_hyphens.append({"page": number, "word": runs[-1]["parts"][-1]})
                at_line_start = False
                continue
            at_line_start = False
            if runs and runs[-1]["rubric"] == red:
                runs[-1]["parts"].append(text)
            else:
                runs.append({"rubric": red, "parts": [text]})

    for page in pages:
        number = page["page"]
        content = [line for line in page["lines"] if line["kind"] == "content"]
        if not content:
            close()
            continue
        pitch = line_pitch(content)
        previous_cy = None
        right_edge = max(line["right"] for line in content)
        for index, line in enumerate(content):
            words = line_words(line)
            if not words:
                continue
            text = " ".join(w["text"] for w in words)
            gap = (line["cy"] - previous_cy) / pitch if previous_cy is not None and pitch else 0.0
            previous_cy = line["cy"]

            if any(text.startswith(start) for page_no, start in specs if page_no == number):
                close()
                notes.append({"page": number, "book_page": number + 3, "text": text})
                continue
            if looks_like_ornament(words, gap, line["cy"] / page["height"]):
                warnings.append(f"ornament: page {number}: dropped {text!r}")
                continue

            # A page break does not end a paragraph: every paragraph of the book begins
            # with an indented line, so the indent alone tells a new paragraph, also on
            # the first line of a page.
            open_word = paragraph["runs"][-1]["parts"][-1] if paragraph and paragraph["runs"] else None
            # A line that continues a broken word never starts a paragraph: a second
            # half in lowercase cannot begin one, and a capital after an unindented
            # line makes a compound with a real hyphen. A capital after an indented
            # line begins a paragraph, and the open word loses its line-break hyphen.
            # Where the edge of the page is a guess, a line that starts in lowercase
            # continues the paragraph: no paragraph of the book begins in lowercase.
            left_gap = words[0]["left"] - margins.get(number, words[0]["left"])
            indented = left_gap >= INDENT_MIN
            broken = open_word is not None and open_word.endswith("-")
            lowercase = number in uncertain and open_word is not None and words[0]["text"][:1].islower()
            continues = lowercase or (broken and not indented)
            kind = "rubric" if all(w["color"] == "red" for w in words) else "paragraph"
            # An instruction in red that runs over the end of its line goes on in the next
            # one: „Господе, помилуј! (дванаест" — „пута)". The next line is red
            # throughout, so it would be taken for a rubric of its own; but it begins in
            # lowercase right after a red passage that no punctuation closes, so it
            # finishes that passage.
            runs = paragraph["runs"] if paragraph is not None else []
            tail = runs[-1] if runs else None
            goes_on = (
                kind == "rubric"
                and tail is not None
                and paragraph["kind"] == "paragraph"
                and paragraph.get("last") == index - 1
                and tail["rubric"]
                and not tail["parts"][-1].endswith((".", "!", "?", ":", ";", ")", "”", "»"))
                and words[0]["text"][:1].islower()
            )
            continues = lowercase or (broken and not indented) or goes_on
            # A heading printed in red over two lines is centred on both of them: its
            # second line is indented like the start of a block, but it continues the first.
            centred = indented and abs(left_gap - (right_edge - line["right"])) <= CENTRED_TOLERANCE
            adjacent = paragraph is not None and paragraph.get("last") == index - 1
            same_block = (
                paragraph is not None
                and paragraph["kind"] == kind
                and (not indented or (kind == "rubric" and adjacent and centred))
            )
            if not (continues or same_block):
                close()
                paragraph = {
                    "kind": kind,
                    "page_start": number,
                    "page_end": number,
                    "runs": [],
                    "last": index,
                }
            paragraph["last"] = index
            paragraph["page_end"] = number
            feed([(w["text"], w["color"] == "red") for w in words], number)
    close()

    return {
        "pages": len(pages),
        "blocks": blocks,
        "footnotes": notes,
        "kept_hyphens": kept_hyphens,
        "warnings": warnings,
    }


# ---- the `clean` step of the command line -----------------------------------------------------------------


def add_parser(subparsers) -> None:
    subparsers.add_parser(
        "clean", help="apply the corrections and join the OCR lines into build/clean/book.json"
    )


def read_overrides(path: pathlib.Path) -> list[dict]:
    """The corrections of ``data/ocr-overrides.json``; none when the file does not exist yet."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise OverrideError(f"{path}: expected a JSON list of corrections")
    return data


def read_footnotes(root: pathlib.Path) -> list[dict]:
    """The footnotes of every structure file, each with ``page`` and ``starts_with``."""
    notes = []
    for path in sorted((root / "data").glob("structure*.toml")):
        with path.open("rb") as handle:
            notes += tomllib.load(handle).get("footnotes", [])
    return notes


def run(args: argparse.Namespace, root: pathlib.Path) -> int:
    """Apply the corrections and write the cleaned text to ``build/clean/book.json``."""
    pages = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / "build" / "ocr").glob("p-*.json"))
    ]
    by_page: dict[int, list[dict]] = {}
    for override in read_overrides(root / "data" / "ocr-overrides.json"):
        by_page.setdefault(override.get("page"), []).append(override)
    missing = sorted(number for number in by_page if number not in {page["page"] for page in pages})
    if missing:
        raise OverrideError(f"corrections for pages without OCR output: {missing}")
    corrected = [apply_overrides(page, by_page.get(page["page"], [])) for page in pages]
    book = clean_book(corrected, read_footnotes(root))
    out = root / "build" / "clean" / "book.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(book, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    count = sum(len(group) for group in by_page.values())
    print(
        f"{len(pages)} pages, {len(book['blocks'])} blocks, {count} corrections applied, "
        f"{len(book['warnings'])} warnings -> {out.relative_to(root)}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m molitvenik_tools.clean")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    options = parser.parse_args()
    raise SystemExit(run(options, options.root))
