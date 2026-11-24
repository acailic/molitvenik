"""ocr.py: Tesseract's output, lines and their kinds, flags, and the page file."""

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from molitvenik_tools import ocr
from PIL import Image

FIXTURE_PAGES = ["p-008", "p-009", "p-022", "p-083", "p-110", "p-127", "p-137", "p-165"]
SERBIAN_LETTERS = set("абвгдђежзијклљмнњопрстћуфхцчџш")
PAGE_HEIGHT = 1639
TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


@pytest.fixture
def in_process_pool(monkeypatch):
    """The step's pool of processes, run in this process instead, so that the workers see a fake."""
    monkeypatch.setattr(ocr, "ProcessPoolExecutor", ThreadPoolExecutor)


def step_args(*argv):
    """Arguments as `molitvenik ocr …` hands them to the step (contract C8)."""
    parser = argparse.ArgumentParser()
    ocr.add_parser(parser.add_subparsers(dest="step", required=True))
    return parser.parse_args(["ocr", *argv])


def tsv(*rows):
    """Tesseract's TSV text for word rows given as
    (block, paragraph, line, text, left, top, width, height, confidence)."""
    lines = [TSV_HEADER]
    for number, (block, par, line, text, left, top, width, height, conf) in enumerate(rows, 1):
        head = f"5\t1\t{block}\t{par}\t{line}\t{number}\t{left}\t{top}\t{width}\t{height}\t{conf}"
        lines.append(f"{head}\t{text}")
    return "\n".join(lines) + "\n"


def word(text, left, top, width=40, height=24, conf=96.0, block=1, par=1, line=1):
    """A word as Tesseract's TSV holds it."""
    return {"text": text, "left": left, "top": top, "width": width, "height": height, "conf": conf,
            "block": block, "par": par, "line": line}


def tokens(*texts):
    return [{"text": text} for text in texts]


def line_at(cy, *texts):
    """One grouped line of words 40 pixels wide whose centre is `cy`."""
    words = [word(text, 100 * index, cy - 12) for index, text in enumerate(texts)]
    return ocr.group_lines(words)[0]


def painted_page():
    """A page image of 80 × 100 pixels with a red block and a black block: two printed words.

    The blocks are far from each other and from the margin, so that resampling leaves
    the middle of each one unchanged."""
    rgb = np.full((100, 80, 3), 255, dtype=np.uint8)
    rgb[20:60, 8:40] = (190, 40, 40)
    rgb[20:60, 44:76] = (0, 0, 0)
    return rgb


RED_WORD = (1, 1, 1, "црвена", 8, 14, 8, 8, 96.0)      # inside the red block, in half-resolution pixels
BLACK_WORD = (1, 1, 1, "црна", 26, 14, 8, 8, 90.0)     # inside the black block
LATIN_E = "црв" + "e" + "на"                           # the first word with a Latin e read for Cyrillic е


class FakeTesseract:
    """Stands in for Tesseract: writes the TSV and TXT of the reading that belongs to the
    segmentation mode and the size of the image it is given, and records every call."""

    def __init__(self, readings):
        self.readings = readings          # {(page segmentation mode, (width, height)): TSV text}
        self.calls = []

    def __call__(self, cmd, **options):
        image, out_base = Path(cmd[1]), Path(cmd[2])
        psm = cmd[cmd.index("--psm") + 1]
        with Image.open(image) as opened:
            key = (psm, opened.size)
        self.calls.append((key, cmd, options))
        Path(f"{out_base}.tsv").write_text(self.readings[key], encoding="utf-8")
        Path(f"{out_base}.txt").write_text("Крв.\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    def modes(self):
        return sorted(psm for (psm, _), _, _ in self.calls)

    def sizes(self):
        return {size for (_, size), _, _ in self.calls}


def test_parse_tsv_keeps_the_rows_that_hold_a_word(tmp_path):
    path = tmp_path / "base.tsv"
    path.write_text(
        TSV_HEADER + "\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t1055\t1639\t-1\t\n"       # the page
        "4\t1\t1\t1\t1\t0\t135\t333\t390\t47\t-1\t\n"       # a line
        "5\t1\t1\t1\t1\t1\t135\t333\t139\t47\t96.5\tбедни\n"
        "5\t1\t1\t1\t1\t2\t300\t333\t225\t47\t91\tучествујем\n"
        "5\t1\t2\t1\t1\t1\t20\t1500\t20\t20\t50\t\n",      # a row without a word
        encoding="utf-8",
    )
    words = ocr.parse_tsv(path)
    assert words == [
        {"text": "бедни", "left": 135, "top": 333, "width": 139, "height": 47, "conf": 96.5,
         "block": 1, "par": 1, "line": 1},
        {"text": "учествујем", "left": 300, "top": 333, "width": 225, "height": 47, "conf": 91.0,
         "block": 1, "par": 1, "line": 1},
    ]


def test_tesseract_is_called_as_the_design_says_and_leaves_no_file(tmp_path, monkeypatch):
    fake = FakeTesseract({("3", (10, 10)): tsv(RED_WORD)})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    Image.new("L", (10, 10)).save(tmp_path / "page.png")
    words = ocr.run_tesseract(tmp_path / "page.png", tmp_path / "out", 3, None)
    ((_, cmd, options),) = fake.calls
    assert cmd == [
        "tesseract", str(tmp_path / "page.png"), str(tmp_path / "out"), "-l", "srp", "--psm", "3",
        "-c", "tessedit_load_sublangs=", "-c", "tessedit_create_tsv=1",
    ]
    assert options["check"] is True
    assert options["env"]["OMP_THREAD_LIMIT"] == "1"
    assert [w["text"] for w in words] == ["црвена"]
    assert not (tmp_path / "out.tsv").exists()
    assert not (tmp_path / "out.txt").exists()


def test_tesseract_is_given_the_model_directory_when_there_is_one(tmp_path, monkeypatch):
    fake = FakeTesseract({("6", (10, 10)): tsv(RED_WORD)})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    Image.new("L", (10, 10)).save(tmp_path / "page.png")
    ocr.run_tesseract(tmp_path / "page.png", tmp_path / "out", 6, "/models/tessdata")
    ((_, cmd, _),) = fake.calls
    assert cmd[-2:] == ["--tessdata-dir", "/models/tessdata"]
    assert cmd[cmd.index("--psm") + 1] == "6"


def test_model_is_looked_up_in_the_given_directory_first(tmp_path):
    assert ocr.resolve_tessdata(None) is None
    assert ocr.resolve_tessdata(tmp_path) is None            # no srp.traineddata there: Tesseract's own path
    (tmp_path / "srp.traineddata").write_bytes(b"")
    assert ocr.resolve_tessdata(tmp_path) == str(tmp_path)


def test_group_lines_keeps_tesseract_lines_in_order_from_the_top():
    words = [
        word("очисти", 150, 530, line=2),
        word("уда", 200, 330),
        word("грехе", 260, 530, line=2),
        word("Господе", 100, 330),
    ]
    lines = ocr.group_lines(words)
    assert [[w["text"] for w in line["words"]] for line in lines] == [
        ["Господе", "уда"],
        ["очисти", "грехе"],
    ]
    assert [(line["cy"], line["h"]) for line in lines] == [(342.0, 24.0), (542.0, 24.0)]


def test_group_lines_of_no_word_is_empty():
    assert ocr.group_lines([]) == []


def test_group_lines_merges_neighbours_that_share_a_visual_line():
    # A centred red label (Tesseract's line 2, centre 344) and the black text to its right
    # (line 1, centre 352, height 20): 8 is less than half of 20.
    words = [
        word("помилуј!", 520, 342, height=20, line=1),
        word("Господе", 400, 342, height=20, line=1),
        word("Онда:", 135, 332, line=2),
    ]
    (line,) = ocr.group_lines(words)
    assert [w["text"] for w in line["words"]] == ["Онда:", "Господе", "помилуј!"]
    assert line["cy"] == 352.0


def test_group_lines_keeps_lines_a_line_pitch_apart_even_beside_a_tall_box():
    # The tall box makes the first line's median height 59, yet half of the smaller
    # height (12) does not bridge the 47.5 pixels between the two centres.
    words = [
        word("човек", 135, 330),
        word("Бо", 260, 300, height=94),
        word("и", 135, 380, line=2),
        word("ми", 180, 380, line=2),
    ]
    lines = ocr.group_lines(words)
    assert [[w["text"] for w in line["words"]] for line in lines] == [["човек", "Бо"], ["и", "ми"]]


def test_line_kinds():
    assert ocr.classify_line(line_at(82, "Молитвено", "правило"), PAGE_HEIGHT) == "header"
    assert ocr.classify_line(line_at(1510, "113"), PAGE_HEIGHT) == "footer"
    assert ocr.classify_line(line_at(1510, "|", "113"), PAGE_HEIGHT) == "footer"
    assert ocr.classify_line(line_at(1500, "•", ".", "•,"), PAGE_HEIGHT) == "ornament"
    assert ocr.classify_line(line_at(800, "113"), PAGE_HEIGHT) == "ornament"
    assert ocr.classify_line(line_at(1500, "Господе", "помилуј!", "40", "пута"), PAGE_HEIGHT) == "content"
    assert ocr.classify_line(line_at(1500, "40", "пута"), PAGE_HEIGHT) == "content"
    assert ocr.classify_line(line_at(800, "Песма", "5."), PAGE_HEIGHT) == "content"


def test_disagreements_of_two_readings_that_agree():
    base = tokens("У", "име", "Оца")
    assert ocr.disagreements(base, tokens("у", "име", "оца")) == set()      # letter case is no difference


def test_word_read_differently_is_flagged():
    base = tokens("удостој", "ме", "Господару", "да")
    assert ocr.disagreements(base, tokens("удостој", "ме", "Господара", "да")) == {2}


def test_word_missing_from_the_other_reading_is_flagged():
    base = tokens("мене", "обитавај", "као")
    assert ocr.disagreements(base, tokens("мене", "као")) == {1}


def test_extra_words_in_the_other_reading_suspect_the_word_before():
    # „њудостој" read as „њ" and „удостој": the first reading is asked about its word before
    base = tokens("и", "удостој", "ме")
    assert ocr.disagreements(base, tokens("и", "њ", "удостој", "ме")) == {0}
    assert ocr.disagreements(tokens("удостој", "ме"), tokens("њ", "удостој", "ме")) == set()


def test_long_run_of_differences_flags_nothing():
    # five words in a row mean that the readings cut the passage differently, not that one word is wrong
    base = tokens("а", "б", "в", "г", "д", "е")
    assert ocr.disagreements(base, tokens("а", "1", "2", "3", "4", "5", "е")) == set()


def test_word_flags():
    assert ocr.word_flags("бедни", 96.4) == []
    assert ocr.word_flags("ч0-", 84.9) == ["low-confidence"]
    assert ocr.word_flags("Beuepe", 96.4) == ["latin-letters"]
    assert ocr.word_flags("ГОСПОДЕ", 96.4) == ["has-inner-caps"]
    assert ocr.word_flags("Ђђаволе", 96.4) == []
    assert ocr.word_flags("Утробе7", 50.0) == ["low-confidence"]
    assert ocr.color_of(0.5) == "red"
    assert ocr.color_of(0.49) == "black"


def rebuilt(page):
    """The lines of a fixture page made again from its words by the step's own functions."""
    words = [dict(w, block=1, par=1, line=index)
             for index, line in enumerate(page["lines"]) for w in line["words"]]
    return [ocr.make_line(line, page["height"]) for line in ocr.group_lines(words)]


@pytest.mark.parametrize("name", FIXTURE_PAGES)
def test_lines_of_the_fixture_pages_are_made_again_as_they_are(load_fixture, name):
    page = load_fixture("ocr", name)
    assert rebuilt(page) == page["lines"]


@pytest.mark.parametrize("name", FIXTURE_PAGES)
def test_page_file_holds_lines_as_contract_c2_says(load_fixture, name):
    page = load_fixture("ocr", name)
    assert page["book_page"] == page["page"] + 3
    lines = rebuilt(page)
    assert [line["cy"] for line in lines] == sorted(line["cy"] for line in lines)
    assert {line["kind"] for line in lines} <= {"content", "header", "footer", "ornament"}
    for line in lines:
        assert line["text"] == " ".join(w["text"] for w in line["words"])
        has_cyrillic = bool(SERBIAN_LETTERS & set(line["text"].lower()))
        if line["kind"] == "content":
            assert has_cyrillic
        if line["kind"] == "ornament":
            assert not has_cyrillic
        if line["kind"] == "header":
            assert line["cy"] < 0.09 * page["height"]


@pytest.mark.parametrize("name", FIXTURE_PAGES)
def test_words_of_the_fixture_pages_carry_the_flags_and_the_colour_of_their_text(load_fixture, name):
    page = load_fixture("ocr", name)
    for line in page["lines"]:
        for w in line["words"]:
            own = [flag for flag in w["flags"] if not flag.startswith("differs:")]
            assert own == ocr.word_flags(w["text"], w["conf"])
            assert w["color"] == ocr.color_of(w["red"])


def test_page_127_has_one_header_and_no_footer(load_fixture):
    kinds = [line["kind"] for line in load_fixture("ocr", "p-127")["lines"]]
    assert kinds.count("header") == 1
    assert "footer" not in kinds


def test_page_165_ends_with_an_ornament_above_the_footnote(load_fixture):
    lines = load_fixture("ocr", "p-165")["lines"]
    ornament, footnote = lines[-2:]
    assert (ornament["kind"], ornament["text"]) == ("ornament", "• . •,")
    assert (footnote["kind"], footnote["text"]) == ("content", "непријатељи моји.")


def test_read_page_makes_the_page_file_and_the_half_resolution_image(tmp_path, monkeypatch):
    source = tmp_path / "n007_w2000.jpg"
    Image.fromarray(painted_page(), "RGB").save(source)
    base = tsv(RED_WORD, BLACK_WORD)
    mode6 = tsv((1, 1, 1, LATIN_E, 8, 14, 8, 8, 96.0), BLACK_WORD)
    fake = FakeTesseract({("3", (40, 50)): base, ("3", (32, 40)): base, ("6", (40, 50)): mode6})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    half = tmp_path / "review" / "img" / "p-008.png"
    page = ocr.read_page(8, source, half, None)
    assert page == {
        "page": 8,
        "book_page": 11,
        "width": 40,
        "height": 50,
        "source_width": 80,
        "source_height": 100,
        "lines": [
            {
                "kind": "content", "cy": 18.0, "top": 14, "bottom": 22, "left": 8, "right": 34,
                "text": "црвена црна",
                "words": [
                    {"text": "црвена", "left": 8, "top": 14, "width": 8, "height": 8, "conf": 96.0,
                     "red": 1.0, "color": "red", "flags": ["differs:psm6"]},
                    {"text": "црна", "left": 26, "top": 14, "width": 8, "height": 8, "conf": 90.0,
                     "red": 0.0, "color": "black", "flags": []},
                ],
            }
        ],
    }
    assert list(page) == ["page", "book_page", "width", "height", "source_width", "source_height", "lines"]
    assert fake.modes() == ["3", "3", "6"]
    assert fake.sizes() == {(40, 50), (32, 40)}
    with Image.open(half) as image:
        assert (image.size, image.mode) == ((40, 50), "RGB")


def test_pdf_page_is_read_at_twice_its_size_without_a_second_scale(tmp_path, monkeypatch):
    source = tmp_path / "p-008.png"
    Image.fromarray(painted_page(), "RGB").save(source)
    base = tsv(RED_WORD, BLACK_WORD)
    fake = FakeTesseract({("3", (160, 200)): base, ("6", (160, 200)): base})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    page = ocr.read_page(8, source, tmp_path / "p-008-half.png", None, scale=2.0, small_scale=None)
    assert fake.modes() == ["3", "6"]
    assert fake.sizes() == {(160, 200)}
    assert (page["width"], page["height"], page["source_width"], page["source_height"]) == (160, 200, 80, 100)


def fetched(monkeypatch, tmp_path, source="archive", image="n007_w2000.jpg"):
    """A root whose pages were fetched: SOURCE.txt and the image of page 8."""
    pages = tmp_path / "build" / "pages"
    pages.mkdir(parents=True)
    (pages / "SOURCE.txt").write_text(source + "\n", encoding="utf-8")
    Image.fromarray(painted_page(), "RGB").save(pages / image)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    return pages


def fake_tesseract(monkeypatch, half=(40, 50), small=(32, 40)):
    """Three readings of the painted page that agree with each other."""
    base = tsv(RED_WORD, BLACK_WORD)
    fake = FakeTesseract({("3", half): base, ("3", small): base, ("6", half): base})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    return fake


def test_step_defaults_to_the_text_pages():
    args = step_args()
    assert (args.first, args.last, args.jobs, args.tessdata) == (8, 177, 8, None)


def test_run_writes_a_page_file_and_the_half_resolution_image(tmp_path, monkeypatch, in_process_pool):
    fetched(monkeypatch, tmp_path)
    fake_tesseract(monkeypatch)
    assert ocr.run(step_args("--first", "8", "--last", "8"), tmp_path) == 0
    page = json.loads((tmp_path / "build" / "ocr" / "p-008.json").read_text(encoding="utf-8"))
    assert (page["page"], page["book_page"]) == (8, 11)
    assert page["lines"][0]["text"] == "црвена црна"
    with Image.open(tmp_path / "build" / "review" / "img" / "p-008.png") as image:
        assert image.size == (40, 50)


def test_run_passes_the_model_directory_to_tesseract(tmp_path, monkeypatch, in_process_pool):
    fetched(monkeypatch, tmp_path)
    fake = fake_tesseract(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()
    (models / "srp.traineddata").write_bytes(b"")
    args = step_args("--first", "8", "--last", "8", "--tessdata", str(models))
    assert ocr.run(args, tmp_path) == 0
    assert {tuple(cmd[-2:]) for _, cmd, _ in fake.calls} == {("--tessdata-dir", str(models))}


def test_run_reads_a_pdf_source_at_twice_its_size(tmp_path, monkeypatch, in_process_pool):
    fetched(monkeypatch, tmp_path, source="/elsewhere/book.pdf", image="p-008.png")
    base = tsv(RED_WORD, BLACK_WORD)
    fake = FakeTesseract({("3", (160, 200)): base, ("6", (160, 200)): base})
    monkeypatch.setattr(ocr.subprocess, "run", fake)
    assert ocr.run(step_args("--first", "8", "--last", "8"), tmp_path) == 0
    assert fake.modes() == ["3", "6"]


def test_run_without_fetched_pages_says_to_fetch(tmp_path, capsys):
    (tmp_path / "build" / "pages").mkdir(parents=True)
    assert ocr.run(step_args("--first", "8", "--last", "8"), tmp_path) == 1
    assert "SOURCE.txt" in capsys.readouterr().err


def test_run_names_the_pages_that_have_no_image(tmp_path, monkeypatch, capsys):
    fetched(monkeypatch, tmp_path)        # the image of page 9 is missing
    assert ocr.run(step_args("--first", "8", "--last", "9"), tmp_path) == 1
    assert "9" in capsys.readouterr().err


def test_run_without_tesseract_names_the_program(tmp_path, monkeypatch, capsys):
    fetched(monkeypatch, tmp_path)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    assert ocr.run(step_args("--first", "8", "--last", "8"), tmp_path) == 1
    assert "tesseract" in capsys.readouterr().err


def test_first_page_after_the_last_is_refused(tmp_path, capsys):
    (tmp_path / "build" / "pages").mkdir(parents=True)
    assert ocr.run(step_args("--first", "10", "--last", "9"), tmp_path) == 1
    assert "--first" in capsys.readouterr().err


def test_page_tesseract_fails_on_is_named_with_what_it_said(tmp_path, monkeypatch, in_process_pool, capsys):
    fetched(monkeypatch, tmp_path)

    def failing(cmd, **options):
        raise subprocess.CalledProcessError(1, cmd, stderr="Error opening data file")

    monkeypatch.setattr(ocr.subprocess, "run", failing)
    assert ocr.run(step_args("--first", "8", "--last", "8"), tmp_path) == 1
    err = capsys.readouterr().err
    assert "page 8" in err
    assert "Error opening data file" in err


def test_step_runs_on_its_own(tmp_path, monkeypatch, in_process_pool):
    # `uv run python -m molitvenik_tools.ocr …` finds the root from the current directory
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    fetched(monkeypatch, tmp_path)
    fake_tesseract(monkeypatch)
    assert ocr.main(["--first", "8", "--last", "8"]) == 0
    assert (tmp_path / "build" / "ocr" / "p-008.json").is_file()
