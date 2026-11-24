"""Assembling the prayer book from the cleaned text and the structure (contracts C6 and C7)."""

import copy
import json

import pytest
from molitvenik_tools.assemble import (
    StructureError,
    assemble,
    length_of,
    load_structure,
    run,
    run_check,
)

MORNING_TITLE = "МОЛИТВЕ ЈУТАРЊЕ"
EVENING_TITLE = "МОЛИТВЕ ПРЕ СПАВАЊА"


def rubric(page, text, end=None):
    return {"kind": "rubric", "page_start": page, "page_end": end or page, "text": text}


def paragraph(page, *runs, end=None):
    return {
        "kind": "paragraph",
        "page_start": page,
        "page_end": end or page,
        "runs": [{"text": text, "rubric": red} for text, red in runs],
    }


def book(*blocks):
    return {"pages": 3, "blocks": list(blocks), "footnotes": [], "kept_hyphens": [], "warnings": []}


def unit(section, slug, **fields):
    return {"id": f"{section}__{slug}", "section": section, "slug": slug, **fields}


BLACK = (False,)

BOOK = book(
    rubric(8, MORNING_TITLE),
    rubric(8, "Ако није свештеник, почиње овако:"),
    paragraph(8, ("Господе Исусе Христе,", False)),
    rubric(8, "Молитва прва, светога Макарија Великог:"),
    paragraph(8, ("Боже, очисти ме грешнога.", False), ("Амин.", False)),
    rubric(9, f"{EVENING_TITLE} Затим:"),
    paragraph(9, ("Господе Исусе Христе, Боже наш, помилуј нас. Амин.", False)),
)

START = unit(
    "jutarnje",
    "pocetak",
    title="Господе Исусе Христе",
    starts_with="Господе Исусе Христе,",
    tags=["u-svako-doba"],
    addressees=["gospod-isus-hrist"],
)
NUMBERED = unit(
    "jutarnje",
    "molitva-1",
    title="Молитва прва",
    heading="Молитва прва",
    author="св. Макарије Велики",
    tags=["pokajanje"],
    addressees=["gospod-isus-hrist"],
)
HEADED = unit("pre-spavanja", "zatim", title="Затим", heading="Затим:", tags=["miran-san"])
UNHEADED = unit(
    "pre-spavanja",
    "jedina",
    title="Једина",
    starts_with="Господе Исусе Христе, Боже наш",
    tags=["miran-san"],
)


def structure(morning=(START, NUMBERED), evening=(HEADED,), last_page=8):
    return {
        "book": {
            "title": "Православни молитвеник",
            "publisher": "Штампарија",
            "place": "Београд",
            "year": 1998,
        },
        "footnotes": [],
        "sections": [
            {
                "id": "jutarnje",
                "title": "Молитве јутарње",
                "first_page": 8,
                "last_page": last_page,
                "units": list(morning),
            },
            {
                "id": "pre-spavanja",
                "title": "Молитве пре спавања",
                "first_page": 9,
                "last_page": 9,
                "units": list(evening),
            },
        ],
    }


# ---- length --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("words", "tier"),
    [(0, "kratka"), (149, "kratka"), (150, "srednja"), (450, "srednja"), (451, "duga")],
)
def test_length_of(words, tier):
    assert length_of(words) == tier


# ---- assembling ---------------------------------------------------------------------------------------


def test_titles_are_dropped_anchors_cut_and_metadata_taken():
    prayers = assemble(BOOK, structure())
    assert prayers["book"] == {
        "title": "Православни молитвеник",
        "publisher": "Штампарија",
        "place": "Београд",
        "year": 1998,
    }
    assert prayers["sections"] == [
        {
            "id": "jutarnje",
            "order": 1,
            "title": "Молитве јутарње",
            "pages": [11, 11],
            "units": ["jutarnje__pocetak", "jutarnje__molitva-1"],
        },
        {
            "id": "pre-spavanja",
            "order": 2,
            "title": "Молитве пре спавања",
            "pages": [12, 12],
            "units": ["pre-spavanja__zatim"],
        },
    ]
    first, second, third = prayers["units"]
    # A unit without a heading owns the instruction printed before its prayer.
    assert first["blocks"] == [
        rubric(8, "Ако није свештеник, почиње овако:"),
        paragraph(8, ("Господе Исусе Христе,", False)),
    ]
    assert (first["bookHeading"], first["words"], first["length"], first["pages"]) == (
        None,
        3,
        "kratka",
        [11, 11],
    )
    assert (first["part"], first["author"], first["order"], first["footnotes"]) == (None, None, 1, [])
    # A unit with a heading loses the block that carries it and keeps its text as heading.
    assert second["blocks"] == [paragraph(8, ("Боже, очисти ме грешнога.", False), ("Амин.", False))]
    assert second["bookHeading"] == "Молитва прва, светога Макарија Великог:"
    assert (second["title"], second["author"], second["order"]) == ("Молитва прва", "св. Макарије Велики", 2)
    assert (second["tags"], second["addressees"], second["words"]) == (
        ["pokajanje"],
        ["gospod-isus-hrist"],
        5,
    )
    # A title that shares its line with a heading: the title goes, the heading stays.
    assert third["bookHeading"] == "Затим:"
    assert third["blocks"] == [paragraph(9, ("Господе Исусе Христе, Боже наш, помилуј нас. Амин.", False))]
    assert third["words"] == 8


def test_words_count_the_prayer_runs_only():
    source = book(
        rubric(8, MORNING_TITLE),
        paragraph(8, ("Господе Исусе Христе,", False), ("(три пута)", True)),
        rubric(8, "Молитва прва, светога Макарија Великог:"),
        paragraph(8, ("Боже.", False)),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    prayers = assemble(source, structure(evening=(UNHEADED,)))
    assert prayers["units"][0]["words"] == 5  # two words of prayer and three of a red instruction
    assert prayers["units"][1]["words"] == 1  # the heading's four words are not counted


def test_pages_and_footnotes_follow_the_blocks():
    source = {
        **book(
            rubric(8, MORNING_TITLE),
            paragraph(8, ("Господе Исусе Христе,", False), end=9),
            rubric(9, "Молитва прва, светога Макарија Великог:"),
            paragraph(9, ("Боже.", False), end=10),
            rubric(11, EVENING_TITLE),
            paragraph(11, ("Господе Исусе Христе, Боже наш.", False)),
        ),
        "footnotes": [
            {"page": 9, "book_page": 12, "text": "непријатељи моји."},
            {"page": 11, "book_page": 14, "text": "друга белешка."},
        ],
    }
    spec = structure(evening=(UNHEADED,))
    spec["sections"][0]["last_page"] = 10  # type: ignore[union-attr]
    spec["sections"][1].update(first_page=11, last_page=11)  # type: ignore[union-attr]
    prayers = assemble(source, spec)
    first, second, third = prayers["units"]
    assert (first["pages"], first["footnotes"]) == ([11, 12], [])
    assert second["pages"] == [12, 13]
    assert second["footnotes"] == [{"marker": "", "text": "непријатељи моји."}]
    assert third["footnotes"] == [{"marker": "", "text": "друга белешка."}]


def test_what_stands_before_a_heading_on_its_line_goes_to_the_end_of_the_previous_unit():
    source = book(
        rubric(8, MORNING_TITLE),
        paragraph(8, ("Господе.", False)),
        rubric(8, "Затим, Молитва друга, истог светитеља:"),
        paragraph(8, ("Боже.", False)),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    morning = (
        unit("jutarnje", "prva", title="Прва", starts_with="Господе.", tags=["pokajanje"]),
        unit("jutarnje", "druga", title="Молитва друга", heading="Молитва друга", tags=["pokajanje"]),
    )
    first, second, _ = assemble(source, structure(morning, (UNHEADED,)))["units"]
    assert second["bookHeading"] == "Молитва друга, истог светитеља:"
    assert second["blocks"] == [paragraph(8, ("Боже.", False))]
    assert first["blocks"] == [paragraph(8, ("Господе. Затим,", False))]


def test_what_stands_between_the_title_and_the_first_heading_stays_as_a_subtitle():
    source = book(
        rubric(8, f"{MORNING_TITLE} Глас 8. Псалам 50."),
        paragraph(8, ("Помилуј ме, Боже.", False)),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    morning = (unit("jutarnje", "psalam", title="Псалам 50", heading="Псалам 50", tags=["pokajanje"]),)
    first = assemble(source, structure(morning, (UNHEADED,)))["units"][0]
    assert first["bookHeading"] == "Псалам 50."
    assert first["blocks"] == [rubric(8, "Глас 8."), paragraph(8, ("Помилуј ме, Боже.", False))]


def test_a_red_line_right_before_a_prayer_is_its_instruction():
    source = book(
        rubric(8, MORNING_TITLE),
        paragraph(8, ("Прва.", False)),
        rubric(8, "Затим ове тропаре:"),
        paragraph(8, ("Уставши од сна.", False)),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    morning = (
        unit("jutarnje", "prva", title="Прва", starts_with="Прва.", tags=["pokajanje"]),
        unit(
            "jutarnje",
            "tropar",
            title="Уставши од сна",
            starts_with="Уставши од сна",
            tags=["pokajanje"],
        ),
    )
    first, second, _ = assemble(source, structure(morning, (UNHEADED,)))["units"]
    assert first["blocks"] == [paragraph(8, ("Прва.", False))]
    assert second["blocks"] == [rubric(8, "Затим ове тропаре:"), paragraph(8, ("Уставши од сна.", False))]


def test_a_prayer_that_is_printed_in_red_is_found_by_its_own_words():
    source = book(
        rubric(8, MORNING_TITLE),
        rubric(8, "затим: Достојно јест заиста блажена Тебе Богородицу."),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    morning = (
        unit(
            "jutarnje",
            "dostojno",
            title="Достојно јест",
            starts_with="затим: Достојно јест",
            tags=["zahvalnost"],
        ),
    )
    first = assemble(source, structure(morning, (UNHEADED,)))["units"][0]
    assert first["blocks"] == [rubric(8, "затим: Достојно јест заиста блажена Тебе Богородицу.")]


def test_an_anchor_that_occurs_twice_needs_the_unit_to_say_which_one_is_meant():
    source = book(
        rubric(8, MORNING_TITLE),
        rubric(8, "Кондак 1"),
        paragraph(8, ("Први.", False)),
        rubric(8, "И опет се чита Икос 1:"),
        rubric(8, "Кондак 1"),
        paragraph(8, ("Први, поново.", False)),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    plain = (unit("jutarnje", "kondak-1", title="Кондак 1", heading="Кондак 1", tags=["zahvalnost"]),)
    with pytest.raises(StructureError, match=r"anchor 'Кондак 1' matched 2 blocks"):
        assemble(source, structure(plain, (UNHEADED,)))
    with pytest.raises(StructureError, match="nth = 3, which does not pick"):
        assemble(source, structure(({**plain[0], "nth": 3},), (UNHEADED,)))
    first = assemble(source, structure(({**plain[0], "nth": 2},), (UNHEADED,)))["units"][0]
    assert first["blocks"] == [
        rubric(8, "Кондак 1"),
        paragraph(8, ("Први.", False)),
        rubric(8, "И опет се чита Икос 1:"),
        paragraph(8, ("Први, поново.", False)),
    ]


def test_the_input_is_left_as_it_was_even_when_the_result_is_changed():
    before = copy.deepcopy((BOOK, structure()))
    prayers = assemble(BOOK, structure())
    prayers["units"][0]["blocks"][1]["runs"].append({"text": "нова реч", "rubric": False})
    prayers["units"][0]["blocks"][1]["runs"][0]["text"] = "промењено"
    assert (BOOK, structure()) == before


# ---- errors of the structure --------------------------------------------------------------------------


def test_an_anchor_must_match_exactly_once():
    twice = book(
        rubric(8, MORNING_TITLE),
        paragraph(8, ("Господе Исусе Христе,", False)),
        rubric(8, "Молитва прва, светога Макарија Великог:"),
        rubric(8, "И опет се чита Молитва прва:"),
        rubric(9, EVENING_TITLE),
        paragraph(9, ("Господе Исусе Христе, Боже наш.", False)),
    )
    with pytest.raises(StructureError, match=r"anchor 'Молитва прва' matched 2 blocks"):
        assemble(twice, structure(evening=(UNHEADED,)))
    nowhere = structure(morning=({**START, "starts_with": "Господе Боже наш"}, NUMBERED))
    with pytest.raises(StructureError, match=r"anchor 'Господе Боже наш' matched 0 blocks"):
        assemble(BOOK, nowhere)


def test_units_must_be_in_book_order():
    with pytest.raises(StructureError, match="section jutarnje: the units are not in book order"):
        assemble(BOOK, structure(morning=(NUMBERED, START)))


def test_a_section_must_start_with_its_title():
    with pytest.raises(StructureError, match="does not start with the title 'Молитве јутарње'"):
        assemble(book(rubric(8, "ДРУГИ НАСЛОВ"), paragraph(8, ("Господе.", False))), structure())
    with pytest.raises(StructureError, match="its first block is not a rubric"):
        assemble(book(paragraph(8, (MORNING_TITLE, False)), paragraph(8, ("Господе.", False))), structure())


def test_a_section_without_text_or_units_is_an_error():
    spec = structure()
    spec["sections"][1].update(first_page=40, last_page=40)  # type: ignore[union-attr]
    with pytest.raises(StructureError, match="no text on PDF pages 40"):
        assemble(BOOK, spec)
    spec = structure()
    spec["sections"][1]["units"] = []
    with pytest.raises(StructureError, match="section pre-spavanja: no units"):
        assemble(BOOK, spec)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"slug": "Молитва-1"}, "not an ASCII slug"),
        ({"heading": "", "starts_with": ""}, "exactly one of heading"),
        ({"heading": "Молитва", "starts_with": "Молитва"}, "exactly one of heading"),
        ({"title": ""}, "no title"),
        ({"tags": []}, "no tag"),
        ({"tags": ["nepoznato"]}, "unknown tag 'nepoznato'"),
        ({"addressees": ["neko"]}, "unknown addressee 'neko'"),
    ],
)
def test_a_unit_that_is_not_well_formed_is_rejected(change, message):
    spec = structure(morning=(START, {**NUMBERED, **change}))
    with pytest.raises(StructureError, match=message):
        assemble(BOOK, spec)


def test_ids_must_be_unique():
    spec = structure()
    spec["sections"][1]["id"] = "jutarnje"
    with pytest.raises(StructureError, match="section id occurs twice: jutarnje"):
        assemble(BOOK, spec)
    spec = structure(morning=(NUMBERED, {**NUMBERED, "heading": "Друга"}))
    with pytest.raises(StructureError, match="unit id occurs twice: jutarnje__molitva-1"):
        assemble(BOOK, spec)


def test_a_structure_without_its_book_table_is_rejected():
    spec = structure()
    del spec["book"]
    with pytest.raises(StructureError, match="no structure file has a \\[book\\] table"):
        assemble(BOOK, spec)


# ---- structure files ----------------------------------------------------------------------------------

TOML_1 = """
[book]
title = "Православни молитвеник"
year = 1998

[[sections]]
id = "jutarnje"
title = "Молитве јутарње"
first_page = 8
last_page = 8

  [[sections.units]]
  slug = "pocetak"
  title = "Господе Исусе Христе"
  starts_with = "Господе Исусе Христе,"
  tags = ["u-svako-doba"]

  [[sections.units]]
  slug = "molitva-1"
  title = "Молитва прва"
  heading = "Молитва прва"
  part = ""
  author = "св. Макарије Велики"
  tags = ["pokajanje"]
  addressees = ["gospod-isus-hrist"]
"""

TOML_2 = """
[[footnotes]]
page = 9
starts_with = "Затим"

[[sections]]
id = "pre-spavanja"
title = "Молитве пре спавања"
first_page = 9
last_page = 9

  [[sections.units]]
  slug = "zatim"
  title = "Затим"
  heading = "Затим:"
  tags = ["miran-san"]
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_structure_merges_several_files(tmp_path):
    first = write(tmp_path / "structure-1.toml", TOML_1)
    second = write(tmp_path / "structure-2.toml", TOML_2)
    loaded = load_structure([first, second])
    assert loaded["book"] == {"title": "Православни молитвеник", "year": 1998}
    assert loaded["footnotes"] == [{"page": 9, "starts_with": "Затим"}]
    assert [section["id"] for section in loaded["sections"]] == ["jutarnje", "pre-spavanja"]
    assert [u["slug"] for u in loaded["sections"][0]["units"]] == ["pocetak", "molitva-1"]
    assert loaded["sections"][0]["units"][1]["author"] == "св. Макарије Велики"
    assert [s["id"] for s in assemble(BOOK, loaded)["sections"]] == ["jutarnje", "pre-spavanja"]


def test_load_structure_needs_a_book_table_and_well_formed_footnotes(tmp_path):
    second = write(tmp_path / "structure-2.toml", TOML_2)
    with pytest.raises(StructureError, match="no structure file has a \\[book\\] table"):
        load_structure([second])
    broken = write(tmp_path / "structure-3.toml", "[[footnotes]]\npage = 9\n")
    with pytest.raises(StructureError, match=r"footnotes.*needs 'page' and 'starts_with'"):
        load_structure([write(tmp_path / "structure-1.toml", TOML_1), broken])


# ---- the steps ----------------------------------------------------------------------------------------


class Args:
    pass


def step_files(tmp_path):
    (tmp_path / "build" / "clean").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "build" / "clean" / "book.json").write_text(
        json.dumps(BOOK, ensure_ascii=False), encoding="utf-8"
    )
    write(tmp_path / "data" / "structure-1.toml", TOML_1)
    write(tmp_path / "data" / "structure-2.toml", TOML_2)
    return tmp_path / "data" / "prayers.json"


def test_the_assemble_step_writes_prayers_json(tmp_path):
    out = step_files(tmp_path)
    assert run(Args(), tmp_path) == 0
    prayers = json.loads(out.read_text(encoding="utf-8"))
    assert [unit["id"] for unit in prayers["units"]] == [
        "jutarnje__pocetak",
        "jutarnje__molitva-1",
        "pre-spavanja__zatim",
    ]
    assert run_check(Args(), tmp_path) == 0


def test_the_assemble_step_refuses_to_write_when_a_check_fails(tmp_path):
    out = step_files(tmp_path)
    dirty = copy.deepcopy(BOOK)
    dirty["blocks"][4]["runs"][1]["text"] = "Amin."  # Latin letters: the anchor above it still matches
    (tmp_path / "build" / "clean" / "book.json").write_text(
        json.dumps(dirty, ensure_ascii=False), encoding="utf-8"
    )
    assert run(Args(), tmp_path) == 2
    assert not out.exists()


def test_the_steps_say_what_is_missing(tmp_path):
    (tmp_path / "data").mkdir(parents=True)
    with pytest.raises(StructureError, match="no data/structure"):
        run(Args(), tmp_path)
    with pytest.raises(StructureError, match="missing: run the assemble step first"):
        run_check(Args(), tmp_path)
    write(tmp_path / "data" / "structure-1.toml", TOML_1)
    with pytest.raises(StructureError, match="is missing: run the clean step first"):
        run(Args(), tmp_path)
