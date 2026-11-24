"""Applying proofreading corrections (contract C4)."""

import pytest
from molitvenik_tools.overrides import OverrideError, apply_overrides, apply_spans


def word(text, left=0, color="black", conf=90.0):
    return {
        "text": text,
        "left": left,
        "top": 100,
        "width": 40,
        "height": 40,
        "conf": conf,
        "red": 1.0 if color == "red" else 0.0,
        "color": color,
        "flags": [],
    }


def line(*words):
    return {
        "kind": "content",
        "cy": 120.0,
        "top": 100,
        "bottom": 140,
        "left": words[0]["left"] if words else 0,
        "right": 700,
        "text": " ".join(w["text"] for w in words),
        "words": list(words),
    }


def page(number, *lines):
    return {"page": number, "book_page": number + 3, "width": 1000, "height": 1600, "lines": list(lines)}


def texts(page_dict):
    return [line_["text"] for line_ in page_dict["lines"]]


def test_one_replacement_keeps_box_colour_and_confidence():
    original = page(
        110,
        line(
            word("бедни", 135),
            word("учествујем", 274, color="red", conf=77.0),
            word("у", 420),
            word("војој", 460),
        ),
    )
    fixed = apply_overrides(
        original, [{"page": 110, "line": "бедни учествујем у војој", "find": "војој", "replace": "Твојој"}]
    )
    assert texts(fixed) == ["бедни учествујем у Твојој"]
    fixed_words = fixed["lines"][0]["words"]
    assert [w["text"] for w in fixed_words] == ["бедни", "учествујем", "у", "Твојој"]
    assert (fixed_words[-1]["left"], fixed_words[-1]["color"], fixed_words[-1]["conf"]) == (
        460,
        "black",
        90.0,
    )
    assert fixed_words[1]["color"] == "red"  # the rubric word keeps its colour
    assert texts(original) == ["бедни учествујем у војој"]  # the original page is left as it was


def test_several_corrections_on_one_line_are_all_applied():
    original = page(
        110,
        line(word("ђао,", 135), word("jep", 240), word("„eBO", 320), word("једем", 480), word("Твоје", 620)),
    )
    fixed = apply_overrides(
        original,
        [
            {"page": 110, "line": "ђао, jep „eBO једем Твоје", "find": "ђао,", "replace": "ћао,"},
            {"page": 110, "line": "ђао, jep „eBO једем Твоје", "find": "jep", "replace": "јер"},
            {"page": 110, "line": "ђао, jep „eBO једем Твоје", "find": "„eBO", "replace": "ево"},
        ],
    )
    assert texts(fixed) == ["ћао, јер ево једем Твоје"]
    assert [w["left"] for w in fixed["lines"][0]["words"]] == [135, 240, 320, 480, 620]


def test_a_missing_word_is_inserted_and_inherits_the_colour():
    original = page(110, line(word("мени", 135), word("обитавај,", 240), word("си", 700, color="red")))
    fixed = apply_overrides(
        original, [{"page": 110, "line": "мени обитавај, си", "find": "си", "replace": "си обе-"}]
    )
    fixed_line = fixed["lines"][0]
    assert [w["text"] for w in fixed_line["words"]] == ["мени", "обитавај,", "си", "обе-"]
    assert [w["color"] for w in fixed_line["words"]] == ["black", "black", "red", "red"]
    assert fixed_line["text"] == "мени обитавај, си обе-"


def test_an_empty_replace_deletes_the_word():
    original = page(22, line(word("дост", 135), word("NOHA", 240), word("неизрециву", 400)))
    fixed = apply_overrides(
        original, [{"page": 22, "line": "дост NOHA неизрециву", "find": "NOHA", "replace": ""}]
    )
    assert texts(fixed) == ["дост неизрециву"]
    assert [w["left"] for w in fixed["lines"][0]["words"]] == [135, 400]


def test_an_empty_replace_can_delete_every_word_of_a_line():
    """A phantom read from the ornament at the end of a section."""
    original = page(105, line(word("ве", 321)), line(word("светог", 135), word("имена.", 240)))
    fixed = apply_overrides(original, [{"page": 105, "line": "ве", "find": "ве", "replace": ""}])
    assert texts(fixed) == ["", "светог имена."]
    assert fixed["lines"][0]["words"] == []


def test_left_moves_the_first_replaced_word_to_where_the_print_shows_it():
    """The OCR lost the first word of the line, so the word after it looked like an indent."""
    original = page(105, line(word("сузама", 328), word("моли", 470)))
    fixed = apply_overrides(
        original,
        [{"page": 105, "line": "сузама моли", "find": "сузама", "replace": "Пето: Са сузама", "left": 137}],
    )
    fixed_words = fixed["lines"][0]["words"]
    assert [w["text"] for w in fixed_words] == ["Пето:", "Са", "сузама", "моли"]
    assert [w["left"] for w in fixed_words] == [137, 328, 328, 470]
    assert fixed["lines"][0]["left"] == 137


def test_left_also_moves_a_word_whose_text_only_changes():
    """„Његовог" lost its first letter, and its box begins where „говог" did."""
    original = page(105, line(word("говог", 193), word("светог", 330), word("имена.", 470)))
    fixed = apply_overrides(
        original,
        [{"page": 105, "line": "говог светог имена.", "find": "говог", "replace": "Његовог", "left": 137}],
    )
    assert [w["left"] for w in fixed["lines"][0]["words"]] == [137, 330, 470]


def test_a_span_that_touches_two_words_keeps_the_box_of_the_first():
    original = page(9, line(word("Господе", 135), word("Исусе", 260), word("Христе,", 380)))
    fixed = apply_overrides(
        original, [{"page": 9, "line": "Господе Исусе Христе,", "find": "Исусе Христе,", "replace": "Исусе,"}]
    )
    fixed_words = fixed["lines"][0]["words"]
    assert [w["text"] for w in fixed_words] == ["Господе", "Исусе,"]
    assert [w["left"] for w in fixed_words] == [135, 260]


def test_the_rubric_flag_turns_the_replaced_words_red_or_black_or_leaves_them():
    original = page(83, line(word("Свети", 135), word("Боже;", 240), word("и", 330), word("по", 380)))
    named = "Свети Боже; и по"
    # "и" alone occurs twice in the line (inside "Свети" too), so the correction is framed with its spaces
    red = apply_overrides(
        original, [{"page": 83, "line": named, "find": " и ", "replace": " и ", "rubric": True}]
    )
    assert [w["color"] for w in red["lines"][0]["words"]] == ["black", "black", "red", "black"]
    assert texts(red) == [named]
    black = apply_overrides(
        original, [{"page": 83, "line": named, "find": " и ", "replace": " и ", "rubric": False}]
    )
    assert [w["color"] for w in black["lines"][0]["words"]] == ["black", "black", "black", "black"]
    kept = apply_overrides(original, [{"page": 83, "line": named, "find": " и ", "replace": " и "}])
    assert [w["color"] for w in kept["lines"][0]["words"]] == ["black", "black", "black", "black"]


def test_a_line_that_is_missing_or_twice_there_is_an_error():
    single = page(110, line(word("иста"), word("иста")))
    twice = page(110, line(word("иста"), word("иста")), line(word("иста"), word("иста")))
    with pytest.raises(OverrideError, match="occurs 0 times, expected exactly once"):
        apply_overrides(single, [{"page": 110, "line": "нема ме", "find": "x", "replace": "y"}])
    with pytest.raises(OverrideError, match="occurs 2 times, expected exactly once"):
        apply_overrides(twice, [{"page": 110, "line": "иста иста", "find": "иста", "replace": "x"}])


def test_a_find_that_is_missing_or_twice_in_its_line_is_an_error():
    single = page(110, line(word("иста"), word("иста")))
    with pytest.raises(OverrideError, match="'њ' occurs 0 times in line"):
        apply_overrides(single, [{"page": 110, "line": "иста иста", "find": "њ", "replace": "н"}])
    with pytest.raises(OverrideError, match="'иста' occurs 2 times in line"):
        apply_overrides(single, [{"page": 110, "line": "иста иста", "find": "иста", "replace": "x"}])


def test_a_correction_marked_for_another_page_or_without_its_fields_is_an_error():
    single = page(110, line(word("иста"), word("иста")))
    with pytest.raises(OverrideError, match="marked for page 9"):
        apply_overrides(single, [{"page": 9, "line": "иста иста", "find": "иста", "replace": "x"}])
    with pytest.raises(OverrideError, match="needs 'find' and 'replace'"):
        apply_overrides(single, [{"page": 110, "line": "иста иста", "replace": "y"}])
    with pytest.raises(OverrideError, match="needs 'find' and 'replace'"):
        apply_overrides(single, [{"page": 110, "line": "иста иста", "find": "", "replace": "y"}])


def test_overlapping_spans_are_an_error():
    target = line(word("иста"), word("иста"))
    with pytest.raises(OverrideError, match="overlapping"):
        apply_spans(target, [(0, 4, "x", None), (2, 7, "y", None)])


def test_a_correction_on_the_real_fixture_page(load_fixture):
    page_110 = load_fixture("ocr", "p-110")
    before = [line_["text"] for line_ in page_110["lines"]]
    fixed = apply_overrides(
        page_110,
        [
            {"page": 110, "line": "ћао, јер ево једем – Твоје", "find": " – ", "replace": " "},
        ],
    )
    after = [line_["text"] for line_ in fixed["lines"]]
    assert "ћао, јер ево једем Твоје" in after
    assert [line_["text"] for line_ in page_110["lines"]] == before


def test_the_rest_of_a_word_stays_attached_when_its_beginning_is_corrected():
    """„скупонени," was read for „скупоцени,": the comma belongs to the word and must not
    become a word of its own."""
    original = page(48, line(word("Исусе", 135), word("скупонени,", 300), word("об-", 520)))
    fixed = apply_overrides(
        original,
        [{"page": 48, "line": "Исусе скупонени, об-", "find": "скупонени", "replace": "скупоцени"}],
    )
    fixed_words = fixed["lines"][0]["words"]
    assert [w["text"] for w in fixed_words] == ["Исусе", "скупоцени,", "об-"]
    assert [w["left"] for w in fixed_words] == [135, 300, 520]


def test_a_replacement_that_begins_inside_a_word_joins_what_precedes_it():
    """The bracket before „Светлости," is an artefact of the border: only the word may remain."""
    original = page(
        21, line(word("почетна", 135), word("вечна", 260), word("(Светлости,", 380), word("у", 560))
    )
    fixed = apply_overrides(
        original,
        [{"page": 21, "line": "почетна вечна (Светлости, у", "find": "(Светлости", "replace": "Светлости"}],
    )
    assert [w["text"] for w in fixed["lines"][0]["words"]] == ["почетна", "вечна", "Светлости,", "у"]
