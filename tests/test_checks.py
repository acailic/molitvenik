"""The text checks of the assembled prayer book."""

import copy

from molitvenik_tools.assemble import assemble
from molitvenik_tools.checks import (
    latin_inside_words,
    run_checks,
    unbalanced,
    unit_texts,
    words_with_inner_capitals,
)
from test_assemble import BOOK, structure

UID = "jutarnje__pocetak"


def clean():
    """A clean prayer book and the cleaned text it was assembled from."""
    return assemble(BOOK, structure()), copy.deepcopy(BOOK)


def with_text(text):
    """The first unit with a second run added to its prayer, in the book as well.

    The run that carries the anchor of the unit stays first, so that the unit
    can still be found.
    """
    prayers, book = clean()
    run = {"text": text, "rubric": False}
    prayers["units"][0]["blocks"][1]["runs"].append(dict(run))
    book["blocks"][2]["runs"].append(dict(run))
    return prayers, book


def with_unit(**changes):
    prayers, book = clean()
    prayers["units"][0] = {**prayers["units"][0], **changes}
    return prayers, book


def test_a_well_formed_book_has_no_problems():
    assert run_checks(*clean()) == []


def test_latin_letters_in_a_word_are_a_problem():
    assert run_checks(*with_text("Господе jep Исусе Христе,")) == [f"{UID} (block 2): Latin letters in 'jep'"]


def test_a_spacing_symbol_left_in_the_text_is_a_problem():
    assert run_checks(*with_text("Господе ~ Исусе")) == [f"{UID} (block 2): spacing symbol left in '~'"]
    assert run_checks(*with_text("Господе| Исусе")) == [f"{UID} (block 2): spacing symbol left in 'Господе|'"]


def test_a_hyphen_left_at_the_edge_of_a_word_is_a_problem():
    for text, word in (("Господе- Исусе", "Господе-"), ("-Исусе Христе", "-Исусе")):
        problems = run_checks(*with_text(text))
        assert problems == [f"{UID} (block 2): hyphen left at the edge of {word!r}"]


def test_a_capital_inside_a_word_is_a_problem():
    assert run_checks(*with_text("Господе ПОМИЛУЈ нас")) == [
        f"{UID} (block 2): capital letter inside 'ПОМИЛУЈ'"
    ]


def test_brackets_and_quotation_marks_must_balance():
    assert run_checks(*with_text("(три пута")) == [f"{UID}: '(' 1 times, ')' 0 times"]
    assert run_checks(*with_text("„Радуј се")) == [f"{UID}: '„' 1 times, '“' 0 times"]


def test_a_unit_needs_its_title_its_tags_and_a_consistent_length():
    assert run_checks(*with_unit(title="")) == [f"{UID}: no title"]
    assert run_checks(*with_unit(tags=[])) == [f"{UID}: no tag"]
    assert run_checks(*with_unit(length="duga")) == [f"{UID}: length 'duga' does not match 3 words"]
    assert run_checks(*with_unit(blocks=[])) == [
        f"{UID}: no block",
        "text lost or repeated: the sections hold 32 words, the units 13, the titles and headings 11",
    ]


def test_a_unit_of_an_unknown_section_is_a_problem():
    assert run_checks(*with_unit(section="nema")) == [
        f"{UID}: unknown section 'nema'",
        "section jutarnje: its units are not listed in book order",
    ]


def test_a_unit_listed_twice_is_a_problem():
    prayers, book = clean()
    prayers["units"].append(copy.deepcopy(prayers["units"][0]))
    problems = run_checks(prayers, book)
    assert [p for p in problems if not p.startswith("text lost")] == [
        f"unit id occurs twice: {UID}",
        "section jutarnje: its units are not listed in book order",
    ]
    assert (
        problems[-1]
        == "text lost or repeated: the sections hold 32 words, the units 29, the titles and headings 11"
    )


def test_text_lost_between_the_book_and_the_units_is_a_problem():
    prayers, book = clean()
    del prayers["units"][1]
    assert run_checks(prayers, book) == [
        "section jutarnje: units listed that do not exist",
        "section jutarnje: its units are not listed in book order",
        "text lost or repeated: the sections hold 32 words, the units 16, the titles and headings 6",
    ]


def test_a_hyphen_removed_at_the_end_of_a_paragraph_is_a_problem_an_ornament_is_not():
    prayers, book = clean()
    book["warnings"] = ["ornament: page 105: dropped 'у'"]
    assert run_checks(prayers, book) == []
    book["warnings"].append("hyphen: page 12: removed a hyphen at the end of a paragraph: 'Амин.-'")
    assert run_checks(prayers, book) == [book["warnings"][1]]


def test_the_footnotes_are_checked_and_counted():
    note = {"marker": "", "text": "непријатељи МОЈИ."}
    prayers, book = with_unit(footnotes=[note])
    book["footnotes"] = [{"page": 8, "book_page": 11, "text": note["text"]}]
    assert run_checks(prayers, book) == [f"{UID} (footnote): capital letter inside 'МОЈИ.'"]
    del book["footnotes"]
    assert run_checks(prayers, book)[-1] == (
        "text lost or repeated: the sections hold 32 words, the units 23, the titles and headings 11"
    )


# ---- the helpers --------------------------------------------------------------------------------------


def test_latin_inside_words():
    assert latin_inside_words("Господе jep Исусе Beuepe") == ["jep", "Beuepe"]
    assert latin_inside_words("Господе Исусе Христе 12") == []


def test_words_with_inner_capitals():
    assert words_with_inner_capitals("ГоСПОДе ПОМИЛУЈ Господе Бог") == ["ГоСПОДе", "ПОМИЛУЈ"]
    assert words_with_inner_capitals("слава Бого-Јавље Твојега") == []
    assert words_with_inner_capitals("Јер Твојег 12а A") == []


def test_unbalanced():
    assert unbalanced("(три пута) „Радуј се“") == []
    assert unbalanced("(три (пута)") == ["'(' 2 times, ')' 1 times"]
    assert unbalanced("„Радуј се“ „Невесто") == ["'„' 2 times, '“' 1 times"]


def test_unit_texts_lists_rubrics_runs_and_footnotes():
    unit = assemble(BOOK, structure())["units"][0]
    assert unit_texts(unit) == [
        ("block 1 (rubric)", "Ако није свештеник, почиње овако:"),
        ("block 2", "Господе Исусе Христе,"),
    ]


# ---- the sample of the site ---------------------------------------------------------------------------


def book_of(prayers):
    """The cleaned text a prayer book of the sample's shape was assembled from."""
    blocks, notes = [], []
    for section in prayers["sections"]:
        page = section["pages"][0] - 3
        blocks.append({"kind": "rubric", "page_start": page, "page_end": page, "text": section["title"]})
    for unit in prayers["units"]:
        first, last = unit["pages"][0] - 3, unit["pages"][1] - 3
        if unit["bookHeading"]:
            blocks.append(
                {"kind": "rubric", "page_start": first, "page_end": first, "text": unit["bookHeading"]}
            )
        blocks += [{**block, "page_start": first, "page_end": last} for block in unit["blocks"]]
        notes += [{"page": first, "book_page": first + 3, "text": note["text"]} for note in unit["footnotes"]]
    return {"pages": 0, "blocks": blocks, "footnotes": notes, "kept_hyphens": [], "warnings": []}


def test_the_sample_of_the_site_is_whole_even_though_its_text_is_raw(load_fixture):
    prayers = load_fixture("site", "prayers.sample")
    problems = run_checks(prayers, book_of(prayers))
    structural = [
        p
        for p in problems
        if p.startswith(("text lost", "unit id", "section ")) or "unknown section" in p or ": no " in p
    ]
    assert structural == []
    # The sample was cut from raw OCR, so the text checks have something to say about it.
    assert any("capital letter inside" in p for p in problems)
