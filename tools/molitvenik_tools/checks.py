"""Checks of the assembled prayer book.

They catch what the cleaning could not settle: Latin letters, spacing symbols
and line-break hyphens left in the text, capitals inside a word, unbalanced
brackets and quotation marks, units without what the site needs, and text that
was lost between the cleaned book and the units.

Every check returns a problem in a list; an empty list means the text is clean.
"""

from __future__ import annotations

import re

from molitvenik_tools.assemble import block_text, length_of

WORD = re.compile(r"[^\W_]+", re.UNICODE)
LATIN = re.compile(r"[A-Za-z]")
SPACING_ONLY = re.compile(r"^[^\w\s]+$", re.UNICODE)
DASH_ONLY = re.compile(r"^[—–]+$")  # a dash between words is print, not a spacing symbol
SPACING_SYMBOLS = "·~|=_•¬#"
PAIRS = (("(", ")"), ("„", "“"))


def unit_texts(unit: dict) -> list[tuple[str, str]]:
    """(where, text) for every text of a unit: its blocks and its footnotes."""
    out = []
    for index, block in enumerate(unit.get("blocks", [])):
        if block.get("kind") == "rubric":
            out.append((f"block {index + 1} (rubric)", block.get("text", "")))
        else:
            for run in block.get("runs", []):
                out.append((f"block {index + 1}", run.get("text", "")))
    for note in unit.get("footnotes", []):
        out.append(("footnote", note.get("text", "")))
    return out


def latin_inside_words(text: str) -> list[str]:
    """The words of a text that contain a Latin letter (the text is Cyrillic)."""
    return [word for word in text.split() if LATIN.search(word)]


def words_with_inner_capitals(text: str) -> list[str]:
    """The words that have a capital letter after their first letter.

    Each half of a word joined by a hyphen is looked at on its own, because a
    compound may legitimately carry a capital in its second half.
    """
    found = []
    for token in text.split():
        for part in WORD.findall(token.replace("-", " ")):
            letters = [char for char in part if char.isalpha()]
            if len(letters) >= 2 and any(char.isupper() for char in letters[1:]):
                found.append(token)
                break
    return found


def unbalanced(text: str) -> list[str]:
    """The brackets and quotation marks whose numbers differ in a text."""
    return [
        f"{open_!r} {text.count(open_)} times, {close!r} {text.count(close)} times"
        for open_, close in PAIRS
        if text.count(open_) != text.count(close)
    ]


def _check_unit(unit: dict, problems: list[str]) -> None:
    uid = unit.get("id", "?")
    if not unit.get("title"):
        problems.append(f"{uid}: no title")
    if not unit.get("tags"):
        problems.append(f"{uid}: no tag")
    if unit.get("length") != length_of(unit.get("words", 0)):
        problems.append(f"{uid}: length {unit.get('length')!r} does not match {unit.get('words')} words")
    if not unit.get("blocks"):
        problems.append(f"{uid}: no block")

    whole = []
    for where, text in unit_texts(unit):
        whole.append(text)
        for word in latin_inside_words(text):
            problems.append(f"{uid} ({where}): Latin letters in {word!r}")
        for word in text.split():
            if (SPACING_ONLY.match(word) and not DASH_ONLY.match(word)) or any(
                symbol in word for symbol in SPACING_SYMBOLS
            ):
                problems.append(f"{uid} ({where}): spacing symbol left in {word!r}")
            elif word.endswith("-") or word.startswith("-"):
                problems.append(f"{uid} ({where}): hyphen left at the edge of {word!r}")
        for word in words_with_inner_capitals(text):
            problems.append(f"{uid} ({where}): capital letter inside {word!r}")
    for counts in unbalanced(" ".join(whole)):
        problems.append(f"{uid}: {counts}")


def run_checks(prayers: dict, book: dict) -> list[str]:
    """Every problem of the assembled prayer book against the cleaned text; empty when clean."""
    problems: list[str] = []
    units = prayers.get("units", [])
    sections = prayers.get("sections", [])
    section_ids = [section.get("id") for section in sections]
    if len(set(section_ids)) != len(section_ids):
        problems.append("a section id occurs twice")

    seen: set[str] = set()
    for unit in units:
        uid = unit.get("id", "?")
        if uid in seen:
            problems.append(f"unit id occurs twice: {uid}")
        seen.add(uid)
        if unit.get("section") not in section_ids:
            problems.append(f"{uid}: unknown section {unit.get('section')!r}")
        _check_unit(unit, problems)

    for section in sections:
        sid = section.get("id")
        listed = section.get("units", [])
        if [uid for uid in listed if uid not in seen]:
            problems.append(f"section {sid}: units listed that do not exist")
        own = [unit["id"] for unit in units if unit.get("section") == sid]
        if own != listed:
            problems.append(f"section {sid}: its units are not listed in book order")

    # No text lost: every word inside the sections is in a unit, except the titles
    # of the sections and the headings of the units, which became metadata.
    ranges = [
        (section["pages"][0] - 3, section["pages"][1] - 3) for section in sections if "pages" in section
    ]
    book_words = sum(
        len(WORD.findall(block_text(block)))
        for block in book.get("blocks", [])
        if any(first <= block["page_start"] <= last for first, last in ranges)
    )
    book_words += sum(
        len(WORD.findall(note["text"]))
        for note in book.get("footnotes", [])
        if any(first <= note["page"] <= last for first, last in ranges)
    )
    unit_words = sum(len(WORD.findall(text)) for unit in units for _, text in unit_texts(unit))
    titles = sum(len(WORD.findall(section.get("title", ""))) for section in sections)
    titles += sum(len(WORD.findall(unit.get("bookHeading") or "")) for unit in units)
    if book_words - unit_words != titles:
        problems.append(
            f"text lost or repeated: the sections hold {book_words} words, the units {unit_words}, "
            f"the titles and headings {titles}"
        )

    problems += [warning for warning in book.get("warnings", []) if warning.startswith("hyphen:")]
    return problems
