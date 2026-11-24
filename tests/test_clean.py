"""Joining OCR lines into the cleaned text of the book (contract C5)."""

import json

import pytest
from molitvenik_tools.clean import (
    clean_book,
    is_artefact,
    join_hyphen,
    line_pitch,
    line_words,
    looks_like_ornament,
    page_margins,
    run,
)
from molitvenik_tools.overrides import OverrideError

MARGIN = 135
INDENT = MARGIN + 90
RIGHT = MARGIN + 730  # the right edge of a full line of the text block
NO_FOOTNOTES: list[dict] = []


def word(text, left, color="black"):
    return {
        "text": text,
        "left": left,
        "top": 100,
        "width": 40,
        "height": 40,
        "conf": 95.0,
        "red": 1.0 if color == "red" else 0.0,
        "color": color,
        "flags": [],
    }


def line(y, *tokens, indent=False, kind="content", right=None, left=None):
    """A line at height ``y``; tokens are texts or (text, colour) pairs.

    ``left`` is where the line starts (the margin, or the indent when
    ``indent`` is set); ``right`` is where it ends. By default the line is
    short, as the last line of a paragraph is.
    """
    words = []
    position = left if left is not None else INDENT if indent else MARGIN
    for token in tokens:
        text, color = (token, "black") if isinstance(token, str) else token
        words.append(word(text, position, color))
        position += 60
    return {
        "kind": kind,
        "cy": float(y),
        "top": y - 20,
        "bottom": y + 20,
        "left": words[0]["left"] if words else 0,
        "right": right if right is not None else position - 20,
        "text": " ".join(w["text"] for w in words),
        "words": words,
    }


def red(tokens):
    """The same tokens, all red."""
    return [(token, "red") for token in tokens]


REFERENCE_PAGES = (5, 6, 7)


def reference_pages():
    """Three pages with full lines at the margin, so that the width of the text block is known."""
    return [
        page(
            number,
            line(200, "реч", right=RIGHT),
            line(254, "реч", right=RIGHT),
            line(308, "реч", right=RIGHT),
        )
        for number in REFERENCE_PAGES
    ]


def own_texts(book):
    """The text of the blocks that are not on the reference pages."""
    return [
        text
        for block, text in zip(book["blocks"], texts(book), strict=True)
        if block["page_start"] not in REFERENCE_PAGES
    ]


def page(number, *lines, height=1600):
    return {"page": number, "book_page": number + 3, "width": 1000, "height": height, "lines": list(lines)}


def run_text(block):
    return " ".join(part["text"] for part in block.get("runs", [{"text": block.get("text", "")}]))


def texts(book):
    return [run_text(block) for block in book["blocks"]]


# ---- small helpers ------------------------------------------------------------------------------------


def test_is_artefact_is_true_only_for_tokens_of_spacing_symbols():
    for token in ("·", "~", "|", "=", "_", "•", "|;", "!|"):
        assert is_artefact(token), token
    for token in ("Господе", "50", "(", ")", "бо-", "...", "–", "—", "_—"):
        assert not is_artefact(token), token


def test_a_dash_between_words_is_printed_and_stays():
    """„схвативши да је Он – Господ“: the book prints dashes, in ordinary gaps. The dashes the
    OCR puts into the wide gaps of justified lines are phantoms; each of them is removed by
    a correction that was checked against the scan, not by the cleaner."""
    page_with_dash = page(37, line(200, "схвативши", "да", "је", "Он", "–", "Господ,", right=RIGHT))
    assert texts(clean_book([*reference_pages(), page_with_dash], NO_FOOTNOTES))[-1].endswith("Он – Господ,")
    assert [w["text"] for w in line_words({"words": [word("—–", 10)]})] == ["—–"]


def test_spacing_symbols_are_stripped_and_a_rest_without_letters_vanishes():
    assert line_words({"words": [word("реч", 10), word("~", 70), word("|реч", 130)]}) == [
        word("реч", 10),
        word("реч", 130),
    ]
    vanished = line_words({"words": [word("|", 10), word("|;", 70), word("_", 130)]})
    assert vanished == []
    apart = line_words({"words": [word(")", 10), word("...", 70)]})
    assert [w["text"] for w in apart] == [")", "..."]


def test_a_word_split_by_a_spacing_symbol_becomes_two_words():
    words = line_words({"words": [word("н| јој,", 97)]})
    assert [w["text"] for w in words] == ["н", "јој,"]
    assert all(w["left"] == 97 for w in words)


def test_join_hyphen_removes_the_hyphen_before_a_lowercase_continuation():
    assert join_hyphen("Утешите-", "љу,") == ("Утешитељу,", False)
    assert join_hyphen("риз-", "ницо") == ("ризницо", False)


def test_join_hyphen_keeps_the_hyphen_before_a_capital_letter():
    assert join_hyphen("Бого-", "Јавље") == ("Бого-Јавље", True)
    assert join_hyphen("српско-", "Хрватска") == ("српско-Хрватска", True)


def test_line_pitch_is_the_usual_distance_between_lines():
    assert line_pitch([line(100, "а"), line(154, "б"), line(208, "в"), line(262, "г")]) == 54
    assert line_pitch([line(100, "а")]) == 0.0


def test_looks_like_ornament_needs_the_gap_the_height_and_almost_no_letters():
    alone = [word("у", MARGIN)]
    assert looks_like_ornament(alone, gap=3.0, height_share=0.8)
    assert not looks_like_ornament(alone, gap=1.0, height_share=0.8)  # right below the text
    assert not looks_like_ornament(alone, gap=3.0, height_share=0.3)  # high on the page
    assert not looks_like_ornament([word("Амин.", MARGIN)], gap=3.0, height_share=0.8)
    assert not looks_like_ornament([word("Крв.", MARGIN)], gap=3.0, height_share=0.8)


# ---- the margin of a page ------------------------------------------------------------------------------


def test_the_edge_of_the_text_block_is_where_the_full_lines_line_up_with_their_width():
    clean = page(
        9,
        line(200, "реч", indent=True, right=RIGHT - 3),
        line(254, "реч", right=RIGHT),
        line(308, "реч", right=RIGHT),
    )
    phantom = page(
        87,
        line(200, "реч", right=RIGHT),
        line(254, "реч", right=RIGHT),
        line(308, "реч", right=RIGHT - 2),
        line(362, "реч", indent=True, right=RIGHT - 5),
        line(416, "н", right=RIGHT - 6),
    )
    phantom["lines"][-1]["words"][0]["left"] = MARGIN - 38  # a phantom word far to the left
    margins = page_margins([*reference_pages(), clean, phantom])
    assert (margins[9], margins[87]) == (MARGIN, MARGIN)


def test_a_lone_continuation_line_still_marks_the_edge():
    lone = page(
        20,
        line(200, "реч", indent=True, right=RIGHT),
        line(254, "реч", right=RIGHT - 4),
        line(308, "реч", indent=True, right=RIGHT),
        line(362, "реч", indent=True, right=RIGHT),
    )
    assert page_margins([*reference_pages(), lone])[20] == MARGIN


def test_a_page_whose_lines_are_all_indented_gets_its_edge_one_indent_to_the_left():
    alone = page(8, line(200, "У", "име", "Оца", indent=True), line(254, "Господе", "Исусе", indent=True))
    margins = page_margins([*reference_pages(), alone])
    assert margins[8] == INDENT - 90
    assert own_texts(clean_book([*reference_pages(), alone], NO_FOOTNOTES)) == ["У име Оца", "Господе Исусе"]


# ---- hyphens and paragraphs ---------------------------------------------------------------------------


def test_a_hyphen_before_a_lowercase_continuation_is_removed():
    book = clean_book(
        [
            page(
                12,
                line(200, "Царе", "небески,", "Утешите-", indent=True),
                line(254, "љу,", "Душе", "истине,"),
            )
        ],
        NO_FOOTNOTES,
    )
    assert texts(book) == ["Царе небески, Утешитељу, Душе истине,"]
    assert book["kept_hyphens"] == []


def test_a_hyphen_before_a_capital_letter_on_an_unindented_line_is_kept_and_recorded():
    book = clean_book(
        [page(20, line(200, "слава", "Бого-", indent=True), line(254, "Јавље"), line(308, "Твојега."))],
        NO_FOOTNOTES,
    )
    assert texts(book) == ["слава Бого-Јавље Твојега."]
    assert book["kept_hyphens"] == [{"page": 20, "word": "Бого-Јавље"}]
    assert book["warnings"] == []


def test_a_hyphen_at_the_end_of_a_paragraph_is_removed_and_reported():
    short = page(
        12,
        line(200, "Очисти", "нас", "од", "сваке", "нечистоте.", "Амин.-", indent=True),
        line(254, "Затим:", indent=True),
    )
    book = clean_book([*reference_pages(), short], NO_FOOTNOTES)
    assert own_texts(book) == ["Очисти нас од сваке нечистоте. Амин.", "Затим:"]
    assert book["warnings"] == ["hyphen: page 12: removed a hyphen at the end of a paragraph: 'Амин.-'"]


def test_a_paragraph_continuing_over_a_page_break_is_one_block():
    pages = [
        page(110, line(200, "мени", "обитавај,", "као", "што", "си", "обе-", indent=True)),
        page(111, line(200, "ћао,", "јер", "ево")),
    ]
    book = clean_book(pages, NO_FOOTNOTES)
    assert len(book["blocks"]) == 1
    block = book["blocks"][0]
    assert (block["page_start"], block["page_end"]) == (110, 111)
    assert run_text(block) == "мени обитавај, као што си обећао, јер ево"


def test_a_page_break_does_not_end_a_paragraph_an_indent_does():
    carried = [
        page(110, line(200, "Пресвета", "Тројице,", indent=True), line(254, "Господе,", "очисти", "грехе")),
        page(111, line(200, "наше;", "Владару,")),
    ]
    book = clean_book(carried, NO_FOOTNOTES)
    assert [(block["page_start"], block["page_end"]) for block in book["blocks"]] == [(110, 111)]
    assert run_text(book["blocks"][0]) == "Пресвета Тројице, Господе, очисти грехе наше; Владару,"
    started = [
        page(110, line(200, "Исцели,", "Господе,", indent=True), line(254, "ране", "душе", "моје.")),
        page(111, line(200, "Ирмос:", "Даваоче", indent=True)),
    ]
    book = clean_book(started, NO_FOOTNOTES)
    assert [(block["page_start"], block["page_end"]) for block in book["blocks"]] == [(110, 110), (111, 111)]


def test_an_indented_line_starts_a_paragraph():
    book = clean_book(
        [
            page(
                9,
                line(200, "светих", "помилуј", "нас."),
                line(254, "Затим:", "Слава", indent=True),
                line(308, "наш,", "слава", "Теби."),
            )
        ],
        NO_FOOTNOTES,
    )
    assert texts(book) == ["светих помилуј нас.", "Затим: Слава наш, слава Теби."]


def test_a_phantom_word_to_the_left_of_a_line_does_not_cut_the_paragraph():
    pages = [
        page(
            87,
            line(200, "реч", "реч", indent=True, right=RIGHT),
            line(254, "реч", "реч", right=RIGHT),
            line(308, "реч", "реч", right=RIGHT),
            line(362, "њ", "реч", "реч", right=RIGHT),
        ),
    ]
    pages[0]["lines"][-1]["words"][0]["left"] = MARGIN - 40
    book = clean_book([*reference_pages(), *pages], NO_FOOTNOTES)
    # The phantom word itself stays in the text: a correction removes it, not the cleaning.
    assert own_texts(book) == ["реч реч реч реч реч реч њ реч реч"]


def test_on_a_page_whose_edge_is_a_guess_a_lowercase_line_continues_the_paragraph():
    pages = [
        page(110, line(200, "Господе,", "очисти", "грехе", indent=True)),
        # one short line only: nothing shows where the edge of this page is
        page(111, line(200, "наше;", "Владару,")),
    ]
    book = clean_book([*reference_pages(), *pages], NO_FOOTNOTES)
    assert own_texts(book) == ["Господе, очисти грехе наше; Владару,"]
    assert [(b["page_start"], b["page_end"]) for b in book["blocks"]][-1] == (110, 111)


def test_on_a_page_with_a_known_edge_the_indent_alone_decides_even_for_a_lowercase_line():
    known = page(20, line(200, "реч", "реч", indent=True, right=RIGHT), line(254, "реч", right=RIGHT))
    book = clean_book([*reference_pages(), known], NO_FOOTNOTES)
    assert own_texts(book) == ["реч реч реч"]
    assert [(b["page_start"], b["page_end"]) for b in book["blocks"]] == [(5, 7), (20, 20)]


# ---- red lines and noise ------------------------------------------------------------------------------


def test_spacing_artefacts_are_removed():
    book = clean_book(
        [page(9, line(200, "Господе", "·", "Исусе", "~", "Христе,", indent=True))], NO_FOOTNOTES
    )
    assert texts(book) == ["Господе Исусе Христе,"]


def test_a_line_that_is_red_throughout_becomes_a_rubric_block():
    book = clean_book([page(9, line(200, *red(["Ако", "није", "свештеник,"]), indent=True))], NO_FOOTNOTES)
    assert book["blocks"] == [
        {"kind": "rubric", "page_start": 9, "page_end": 9, "text": "Ако није свештеник,"}
    ]


def test_an_instruction_printed_in_red_over_several_lines_is_one_rubric_block():
    book = clean_book(
        [
            page(
                8,
                line(200, *red(["Пренувши", "се", "из", "сна,", "устани", "одмах,", "и"]), indent=True),
                line(254, *red(["сабравши", "ум,", "реци", "са", "побожношћу", "и", "стра-"])),
                line(308, *red(["хом", "Божјим,", "крстећи", "се:"])),
            )
        ],
        NO_FOOTNOTES,
    )
    assert texts(book) == [
        "Пренувши се из сна, устани одмах, и сабравши ум, реци са побожношћу и страхом Божјим, крстећи се:"
    ]


def test_an_indented_red_line_begins_a_new_rubric_block():
    rubrics = page(99, line(200, *red(["Слава:"]), indent=True), line(254, *red(["И", "сада:"]), indent=True))
    assert own_texts(clean_book([*reference_pages(), rubrics], NO_FOOTNOTES)) == ["Слава:", "И сада:"]


def test_a_heading_printed_in_red_over_two_centred_lines_is_one_rubric_block():
    heading = page(
        149,
        line(200, "Реч", indent=True, right=RIGHT),
        line(254, *red(["Молитва", "десета,"]), left=MARGIN + 239, right=RIGHT - 241),
        line(308, *red(["светога", "Јована", "Дамаскина:"]), left=MARGIN + 154, right=RIGHT - 158),
        line(362, "Пред", "дверима", indent=True, right=RIGHT),
    )
    book = clean_book([*reference_pages(), heading], NO_FOOTNOTES)
    own = [block for block in book["blocks"] if block["page_start"] == 149]
    assert [(block["kind"], block["page_start"]) for block in own] == [
        ("paragraph", 149),
        ("rubric", 149),
        ("paragraph", 149),
    ]
    assert own[1]["text"] == "Молитва десета, светога Јована Дамаскина:"
    assert own[2]["runs"] == [{"text": "Пред дверима", "rubric": False}]


def test_an_inline_red_passage_gives_two_runs():
    book = clean_book(
        [page(9, line(254, ("Затим:", "red"), "Слава", "Теби", "Боже", indent=True))], NO_FOOTNOTES
    )
    assert book["blocks"][0]["kind"] == "paragraph"
    assert book["blocks"][0]["runs"] == [
        {"text": "Затим:", "rubric": True},
        {"text": "Слава Теби Боже", "rubric": False},
    ]


def test_a_red_line_that_goes_on_from_the_red_end_of_a_line_joins_its_paragraph():
    """„Господе, помилуј!" is printed black, „(дванаест" red, and the red „пута)" of the
    next line finishes the instruction. The first line of the page is full, so the
    margin is known and the lowercase start alone would not join anything."""
    lines = page(
        11,
        line(146, "реч", right=RIGHT),
        line(200, "Богородицом."),
        line(254, "Господе,", "помилуј!", ("(дванаест", "red"), indent=True),
        line(308, *red(["пута)"])),
    )
    book = clean_book([*reference_pages(), lines], NO_FOOTNOTES)
    assert [
        (block["kind"], block["page_start"]) for block in book["blocks"] if block["page_start"] == 11
    ] == [("paragraph", 11)]
    assert book["blocks"][-1]["runs"] == [
        {"text": "Господе, помилуј!", "rubric": False},
        {"text": "(дванаест пута)", "rubric": True},
    ]


def test_a_red_line_that_begins_with_a_capital_after_the_same_line_is_a_rubric_of_its_own():
    lines = page(
        84,
        line(146, "реч", right=RIGHT),
        line(200, "ханскога."),
        line(254, "Господе,", "помилуј!", ("(дванаест", "red"), indent=True),
        line(308, *red(["Молитва", "прва,", "светога", "Макарија", "Великог"])),
    )
    book = clean_book([*reference_pages(), lines], NO_FOOTNOTES)
    assert [
        (block["kind"], block["page_start"]) for block in book["blocks"] if block["page_start"] == 84
    ] == [
        ("paragraph", 84),
        ("rubric", 84),
    ]
    assert book["blocks"][-2]["runs"][-1] == {"text": "(дванаест", "rubric": True}
    assert book["blocks"][-1]["text"] == "Молитва прва, светога Макарија Великог"


def test_a_red_line_after_a_red_run_that_ends_a_sentence_is_a_rubric_of_its_own():
    lines = page(
        125,
        line(146, "реч", right=RIGHT),
        line(200, "Господе,", "помилуј!", ("(три", "red"), ("пута).", "red"), indent=True),
        line(254, *red(["И", "ови", "тропари,", "глас", "8:"])),
    )
    book = clean_book([*reference_pages(), lines], NO_FOOTNOTES)
    assert [
        (block["kind"], block["page_start"]) for block in book["blocks"] if block["page_start"] == 125
    ] == [
        ("paragraph", 125),
        ("rubric", 125),
    ]
    assert book["blocks"][-1]["text"] == "И ови тропари, глас 8:"


def test_a_red_line_in_lowercase_after_a_black_end_of_a_line_is_a_rubric_of_its_own():
    lines = page(
        126,
        line(146, "реч", right=RIGHT),
        line(200, "недостојни", "смам", indent=True),
        line(254, *red(["и", "с", "Многобројна"])),
    )
    book = clean_book([*reference_pages(), lines], NO_FOOTNOTES)
    assert [
        (block["kind"], block["page_start"]) for block in book["blocks"] if block["page_start"] == 126
    ] == [
        ("paragraph", 126),
        ("rubric", 126),
    ]
    assert book["blocks"][-1]["text"] == "и с Многобројна"


def test_an_instruction_in_red_that_runs_over_two_line_ends_is_one_paragraph():
    lines = page(
        127,
        line(146, "реч", right=RIGHT),
        line(200, "Христа", "Бога", indent=True, right=RIGHT),
        line(254, ("Онда:", "red"), "Господе", "помилуј!", ("40", "red"), ("пута", "red")),
        line(308, *red(["и", "поклона", "колико", "хођеш."])),
        line(362, *red(["Затим", "одмах", "ове", "стихове:"])),
    )
    book = clean_book([*reference_pages(), lines], NO_FOOTNOTES)
    assert [
        (block["kind"], block["page_start"]) for block in book["blocks"] if block["page_start"] == 127
    ] == [
        ("paragraph", 127),
        ("rubric", 127),
    ]
    # „хођеш." closes the sentence, so the next red line, which begins with a capital,
    # is an instruction of its own.
    assert book["blocks"][-2]["runs"] == [
        {"text": "Христа Бога", "rubric": False},
        {"text": "Онда:", "rubric": True},
        {"text": "Господе помилуј!", "rubric": False},
        {"text": "40 пута и поклона колико хођеш.", "rubric": True},
    ]
    assert book["blocks"][-1]["text"] == "Затим одмах ове стихове:"


def test_an_ornament_read_as_a_word_is_dropped_with_a_warning():
    lines = [line(600 + 54 * index, "реч", "реч", "реч", indent=(index == 0)) for index in range(8)]
    lines.append(line(1200, "у"))
    book = clean_book([page(105, *lines)], NO_FOOTNOTES)
    assert texts(book) == [" ".join(["реч"] * 24)]
    assert book["warnings"] == ["ornament: page 105: dropped 'у'"]


def test_an_ornament_high_on_the_page_or_right_below_the_text_is_kept():
    for lines in (
        [line(200, "реч", indent=True), line(254, "реч"), line(308, "у")],
        [line(600, "реч", indent=True), line(654, "реч"), line(700, "у")],
    ):
        book = clean_book([page(105, *lines)], NO_FOOTNOTES)
        assert book["warnings"] == []
        assert texts(book)[0].endswith("у")


# ---- the real pages of the fixtures -------------------------------------------------------------------


def test_the_running_title_and_the_page_number_are_not_in_the_text(load_fixture):
    book = clean_book([load_fixture("ocr", "p-127")], NO_FOOTNOTES)
    lines = texts(book)
    assert not any(text.startswith("Молитвено правило пред") for text in lines)
    assert not any(text.strip() == "130" for text in lines)
    assert any("Вечере" in text for text in lines)


def test_the_footnote_is_set_apart(load_fixture):
    pages = [load_fixture("ocr", "p-165")]
    notes = [{"page": 165, "starts_with": "непријатељи моји"}]
    book = clean_book(pages, notes)
    assert book["footnotes"] == [{"page": 165, "book_page": 168, "text": "непријатељи моји."}]
    assert all("непријатељи" not in text for text in texts(book))
    without = clean_book(pages, NO_FOOTNOTES)
    assert any("непријатељи" in text for text in texts(without))


def test_the_fixture_pages_clean_into_well_formed_blocks(load_fixture):
    names = ["p-008", "p-009", "p-022", "p-083", "p-110", "p-127", "p-137", "p-165"]
    pages = [load_fixture("ocr", name) for name in names]
    book = clean_book(pages, [{"page": 165, "starts_with": "непријатељи моји"}])
    assert book["pages"] == 8
    assert book["blocks"]
    for block in book["blocks"]:
        assert block["kind"] in ("paragraph", "rubric")
        assert block["page_start"] <= block["page_end"]
        if block["kind"] == "paragraph":
            assert block["runs"] and all(
                run["text"] and run["text"].strip() == run["text"] for run in block["runs"]
            )
        else:
            assert block["text"].strip() == block["text"] and block["text"]
    joined = " ".join(texts(book))
    for symbol in "·~|=#":
        assert symbol not in joined, symbol
    # four paragraphs and the rubric line "Песма 5." between them, as the page shows
    on_110 = [block["kind"] for block in book["blocks"] if block["page_start"] == 110]
    assert on_110 == ["paragraph", "paragraph", "rubric", "paragraph", "paragraph"]
    # the three red lines of the instruction on the title page are one block
    first = [block for block in book["blocks"] if block["page_start"] == 8][:2]
    assert [block["text"] for block in first] == [
        "МОЛИТВЕ ЈУТАРЊЕ",
        "Пренувши се из сна, устани одмах, и сабравши ум, реци са побожношћу и страхом Божјим, крстећи се:",
    ]


def test_a_real_page_keeps_its_paragraph_together(load_fixture):
    book = clean_book([load_fixture("ocr", "p-110")], NO_FOOTNOTES)
    dense = texts(book)
    assert dense[0] == (
        "Исцели, Господе, ране душе моје и освети ме целог; и удостој ме, Господару, да и ја "
        "бедни учествујем у Твојој божанској Вечери Тајној."
    )
    assert dense[1] == (
        "Богородичан: Умилостиви, Владарко, и према мени Онога који је од утробе Твоје, и "
        "сачувај мене, слугу Твог, чистим и непорочним, да бих се, примивши духовни бисер, осветио."
    )


# ---- the step -----------------------------------------------------------------------------------------


class Args:
    pass


def write_step_files(tmp_path, fixture_page, overrides):
    (tmp_path / "build" / "ocr").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    source = tmp_path / "build" / "ocr" / "p-009.json"
    source.write_text(json.dumps(fixture_page, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "ocr-overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
    return tmp_path / "build" / "clean" / "book.json"


def test_the_clean_step_writes_book_json_and_applies_the_corrections(tmp_path, load_fixture):
    out = write_step_files(
        tmp_path,
        load_fixture("ocr", "p-009"),
        [
            {"page": 9, "line": "Затим Слава Теби Боже", "find": "Затим", "replace": "Затим:"},
        ],
    )
    assert run(Args(), tmp_path) == 0
    book = json.loads(out.read_text(encoding="utf-8"))
    rubric_runs = [
        part
        for block in book["blocks"]
        if block["kind"] == "paragraph"
        for part in block["runs"]
        if part["rubric"]
    ]
    assert {"text": "Затим:", "rubric": True} in rubric_runs


def test_the_clean_step_fails_when_a_correction_names_a_page_without_ocr(tmp_path, load_fixture):
    write_step_files(
        tmp_path,
        load_fixture("ocr", "p-009"),
        [
            {"page": 999, "line": "иста иста", "find": "а", "replace": "б"},
        ],
    )
    with pytest.raises(OverrideError, match=r"pages without OCR output: \[999\]"):
        run(Args(), tmp_path)


def test_a_footnote_takes_its_marker_from_the_structure():
    page_with_note = page(
        165, line(200, "реч", right=RIGHT), line(254, "реч", indent=True), line(1500, "непријатељи", "моји.")
    )
    book = clean_book(
        [*reference_pages(), page_with_note], [{"page": 165, "starts_with": "непријатељи", "marker": "*"}]
    )
    assert book["footnotes"] == [{"page": 165, "book_page": 168, "text": "непријатељи моји.", "marker": "*"}]
