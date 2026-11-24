"""Assemble the prayer book: the cleaned text and the curated structure give
``data/prayers.json`` (contract C7).

The structure (``data/structure*.toml``) lists the sections of the book and, for
every section, its units in book order with the anchor that starts each one. A
``heading`` anchor is text of a red heading; the block that carries it becomes
the heading of the unit and leaves its text. A ``starts_with`` anchor is the
opening of a prayer that has no heading of its own.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re
import tomllib

TAGS = frozenset(
    {
        "pokajanje",
        "zahvalnost",
        "zastita",
        "miran-san",
        "za-pokojne",
        "uz-obrok",
        "u-nevolji",
        "u-svako-doba",
    }
)
ADDRESSEES = frozenset(
    {
        "gospod-isus-hrist",
        "bog-otac",
        "presveti-duh",
        "presveta-trojica",
        "presveta-bogorodica",
        "andjeo-cuvar",
        "casni-krst",
    }
)
SLUG = re.compile(r"^[a-z0-9-]+$")
WORD = re.compile(r"[^\W_]+", re.UNICODE)
SHORT = 150  # under this many words a prayer is "kratka"
LONG = 450  # over this many words it is "duga"


class StructureError(ValueError):
    """The curated structure does not fit the cleaned text, or is not well formed."""


def length_of(words: int) -> str:
    """The length tier of a prayer (about 150 words a minute)."""
    if words < SHORT:
        return "kratka"
    if words <= LONG:
        return "srednja"
    return "duga"


def tokens(text: str) -> list[str]:
    """The words of a text: runs of letters and digits."""
    return WORD.findall(text)


def folded(text: str) -> str:
    """A text reduced to its letters and digits, in lower case, to compare headings."""
    return " ".join(tokens(text.casefold()))


def block_text(block: dict) -> str:
    if block["kind"] == "rubric":
        return block["text"]
    return " ".join(run["text"] for run in block["runs"])


# ---- the structure files -------------------------------------------------------------------------------


def validate_structure(structure: dict) -> None:
    """Check that a structure is well formed (contract C6); raise ``StructureError`` if it is not."""
    if "book" not in structure:
        raise StructureError("no structure file has a [book] table")
    for note in structure.get("footnotes", []):
        if "page" not in note or "starts_with" not in note:
            raise StructureError(f"[[footnotes]] needs 'page' and 'starts_with': {note!r}")

    section_ids: set[str] = set()
    unit_ids: set[str] = set()
    for section in structure.get("sections", []):
        sid = section.get("id", "")
        if not SLUG.match(sid):
            raise StructureError(f"section id is not an ASCII slug: {sid!r}")
        if sid in section_ids:
            raise StructureError(f"section id occurs twice: {sid}")
        section_ids.add(sid)
        for key in ("title", "first_page", "last_page"):
            if key not in section:
                raise StructureError(f"section {sid} has no {key}")
        if section["last_page"] < section["first_page"]:
            raise StructureError(f"section {sid}: last_page is before first_page")
        for unit in section.get("units", []):
            slug = unit.get("slug", "")
            uid = f"{sid}__{slug}"
            if not SLUG.match(slug):
                raise StructureError(f"unit slug is not an ASCII slug: {uid!r}")
            if uid in unit_ids:
                raise StructureError(f"unit id occurs twice: {uid}")
            unit_ids.add(uid)
            heading, starts = unit.get("heading", ""), unit.get("starts_with", "")
            if bool(heading) == bool(starts):
                raise StructureError(f"{uid}: set exactly one of heading / starts_with")
            nth = unit.get("nth", 1)
            if not isinstance(nth, int) or isinstance(nth, bool) or nth < 1:
                raise StructureError(f"{uid}: nth must be a positive whole number")
            if not unit.get("title"):
                raise StructureError(f"{uid}: no title")
            tags = unit.get("tags", [])
            if not tags:
                raise StructureError(f"{uid}: no tag")
            for tag in tags:
                if tag not in TAGS:
                    raise StructureError(f"{uid}: unknown tag {tag!r}")
            for who in unit.get("addressees", []):
                if who not in ADDRESSEES:
                    raise StructureError(f"{uid}: unknown addressee {who!r}")


def load_structure(paths: list[pathlib.Path]) -> dict:
    """Merge the structure files (contract C6) and check that they are well formed."""
    book: dict | None = None
    footnotes: list[dict] = []
    sections: list[dict] = []
    for path in paths:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        if book is None and "book" in data:
            book = data["book"]
        footnotes += data.get("footnotes", [])
        sections += data.get("sections", [])
    structure: dict = {"footnotes": footnotes, "sections": sections}
    if book is not None:
        structure["book"] = book
    validate_structure(structure)
    return structure


# ---- assembling ---------------------------------------------------------------------------------------


def without_title(text: str, title: str, sid: str) -> str:
    """The text of a section's first block without the title of the section.

    The title may share its block with the heading that follows it on the title
    page; that heading is what remains.
    """
    words, title_words = text.split(), tokens(title)
    head = tokens(" ".join(words[: len(title_words)]))
    if [word.casefold() for word in head] != [word.casefold() for word in title_words]:
        raise StructureError(
            f"section {sid}: its first line does not start with the title {title!r}: {text!r}"
        )
    return " ".join(words[len(title_words) :])


def heading_pattern(heading: str) -> re.Pattern[str]:
    """A heading as a whole phrase inside the text of a red line."""
    return re.compile(rf"(?<!\w){re.escape(heading)}(?!\w)")


def find_anchor(blocks: list[dict], unit: dict, uid: str, nth: int | None = None) -> int:
    """The index of the block where a unit starts.

    A ``heading`` anchor is looked for in the red lines, a ``starts_with`` anchor
    at the beginning of any block. It must occur once; when it occurs more than
    once, the unit has to say with ``nth`` which occurrence is meant (an akathist
    ends by repeating its first kontakion and ikos).
    """
    heading, starts = unit.get("heading", ""), unit.get("starts_with", "")
    if heading:
        pattern = heading_pattern(heading)
        hits = [
            index
            for index, block in enumerate(blocks)
            if block["kind"] == "rubric" and pattern.search(block["text"])
        ]
    else:
        hits = [index for index, block in enumerate(blocks) if block_text(block).startswith(starts)]
    anchor = heading or starts
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1 and nth is not None and 1 <= nth <= len(hits):
        return hits[nth - 1]
    raise StructureError(
        f"{uid}: anchor {anchor!r} matched {len(hits)} blocks, expected exactly one"
        + (f"; the unit says nth = {nth}, which does not pick one of them" if nth is not None else "")
    )


def make_unit(section: dict, order: int, spec: dict, blocks: list[dict]) -> dict:
    sid, slug = section["id"], spec["slug"]
    first, last = blocks[0]["page_start"], blocks[-1]["page_end"]
    words = sum(
        len(tokens(run["text"])) for block in blocks if block["kind"] == "paragraph" for run in block["runs"]
    )
    return {
        "id": f"{sid}__{slug}",
        "section": sid,
        "order": order,
        "title": spec["title"],
        "bookHeading": spec.get("_book_heading") or None,
        "part": spec.get("part") or None,
        "author": spec.get("author") or None,
        "pages": [first + 3, last + 3],
        "addressees": list(spec.get("addressees", [])),
        "tags": list(spec.get("tags", [])),
        "words": words,
        "length": length_of(words),
        "blocks": blocks,
        "footnotes": [],
    }


def attach_footnotes(units: list[dict], notes: list[dict]) -> None:
    """Give every footnote to the last unit whose pages hold the page it is printed on.

    A footnote stands at the foot of its page, so when two units share that
    page it belongs to the one that ends on it.
    """
    for note in notes:
        holders = [unit for unit in units if unit["pages"][0] - 3 <= note["page"] <= unit["pages"][1] - 3]
        if holders:
            holders[-1]["footnotes"].append({"marker": note.get("marker", ""), "text": note["text"]})


def assemble(book: dict, structure: dict) -> dict:
    """The prayer book of contract C7 from the cleaned text and the curated structure."""
    validate_structure(structure)
    blocks = book["blocks"]
    sections_out: list[dict] = []
    units_out: list[dict] = []
    for order, section in enumerate(structure["sections"], 1):
        sid = section["id"]
        first, last = section["first_page"], section["last_page"]
        own = [block for block in blocks if first <= block["page_start"] <= last]
        if not own:
            raise StructureError(f"section {sid}: no text on PDF pages {first}–{last}")
        if own[0]["kind"] != "rubric":
            raise StructureError(f"section {sid}: its first block is not a rubric with the title: {own[0]!r}")
        remainder = without_title(own[0]["text"], section["title"], sid)
        own = ([{**own[0], "text": remainder}] if remainder else []) + own[1:]

        specs = section.get("units", [])
        if not specs:
            raise StructureError(f"section {sid}: no units")
        starts = [find_anchor(own, spec, f"{sid}__{spec.get('slug', '')}", spec.get("nth")) for spec in specs]
        if any(later < sooner for sooner, later in zip(starts, starts[1:], strict=False)):
            raise StructureError(f"section {sid}: the units are not in book order")

        # A unit owns the blocks from its anchor up to the anchor of the next unit,
        # except that a red line right before its anchor is the instruction that
        # introduces it, so the unit begins there. The first unit owns the title
        # page from the title on.
        begins = list(starts)
        begins[0] = 0
        for index in range(1, len(specs)):
            before = starts[index] - 1
            if own[before]["kind"] == "rubric" and before > starts[index - 1]:
                begins[index] = before
        bounds = [*begins[1:], len(own)]

        section_units = []
        for index, spec in enumerate(specs):
            # Deep copies: the units must not share their runs with the cleaned text.
            piece = [copy.deepcopy(block) for block in own[begins[index] : bounds[index]]]
            spec = dict(spec)
            if spec.get("heading"):
                anchor_index = starts[index] - begins[index]
                carrier = piece[anchor_index]
                match = heading_pattern(spec["heading"]).search(carrier["text"])
                before, after = carrier["text"][: match.start()], carrier["text"][match.start() :]
                spec["_book_heading"] = after
                del piece[anchor_index]
                if before.strip():
                    tail = before.strip()
                    if not section_units:
                        # On the title page it is the subtitle of the section.
                        piece.insert(0, {**carrier, "text": tail})
                    else:
                        # Else it is the end of what comes before: "… (дванаест
                        # пута) Молитва прва…". It goes to the end of the previous unit.
                        last_block = section_units[-1]["blocks"][-1]
                        if last_block["kind"] == "rubric":
                            last_block["text"] = f"{last_block['text']} {tail}"
                        else:
                            last_block["runs"][-1]["text"] = f"{last_block['runs'][-1]['text']} {tail}"
            if not piece:
                raise StructureError(f"{sid}__{spec.get('slug')}: the unit has no text")
            section_units.append(make_unit(section, index + 1, spec, piece))
        attach_footnotes(
            section_units,
            [note for note in book.get("footnotes", []) if first <= note["page"] <= last],
        )

        info = section | {
            "order": order,
            "pages": [first + 3, last + 3],
            "units": [unit["id"] for unit in section_units],
        }
        sections_out.append({key: info[key] for key in ("id", "order", "title", "pages", "units")})
        units_out += section_units

    return {"book": dict(structure["book"]), "sections": sections_out, "units": units_out}


# ---- the `assemble` and `check` steps ------------------------------------------------------------------


def add_parser(subparsers) -> None:
    subparsers.add_parser("assemble", help="build data/prayers.json from the cleaned text and the structure")
    subparsers.add_parser("check", help="run the text checks on the assembled prayer book")


def load_book(root: pathlib.Path) -> dict:
    path = root / "build" / "clean" / "book.json"
    if not path.exists():
        raise StructureError(f"{path} is missing: run the clean step first")
    return json.loads(path.read_text(encoding="utf-8"))


def structure_paths(root: pathlib.Path) -> list[pathlib.Path]:
    paths = sorted((root / "data").glob("structure*.toml"))
    if not paths:
        raise StructureError("no data/structure*.toml: the structure of the book is not curated yet")
    return paths


def report(problems: list[str]) -> None:
    for problem in problems:
        print(f"  {problem}")
    print(f"{len(problems)} problem{'s' if problems != 1 else ''}")


def run(args: argparse.Namespace, root: pathlib.Path) -> int:
    """Write ``data/prayers.json``; exit 2 when a text check fails."""
    from molitvenik_tools.checks import run_checks

    structure = load_structure(structure_paths(root))
    prayers = assemble(load_book(root), structure)
    problems = run_checks(prayers, load_book(root))
    if problems:
        report(problems)
        return 2
    out = root / "data" / "prayers.json"
    out.write_text(json.dumps(prayers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    words = sum(unit["words"] for unit in prayers["units"])
    print(
        f"{len(prayers['sections'])} sections, {len(prayers['units'])} units, {words} words "
        f"-> {out.relative_to(root)}"
    )
    return 0


def run_check(args: argparse.Namespace, root: pathlib.Path) -> int:
    """Run the text checks on the files as they are; exit 2 when one fails."""
    from molitvenik_tools.checks import run_checks

    path = root / "data" / "prayers.json"
    if not path.exists():
        raise StructureError(f"{path} is missing: run the assemble step first")
    problems = run_checks(json.loads(path.read_text(encoding="utf-8")), load_book(root))
    report(problems)
    return 2 if problems else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m molitvenik_tools.assemble")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    options = parser.parse_args()
    raise SystemExit(run(options, options.root))
