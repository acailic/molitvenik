"""Tests for the reviewer material: hints, marked lines, strips, comparison and corrections."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest
from molitvenik_tools import review
from PIL import Image

REPO = Path(__file__).resolve().parents[1]

# Reasons of suspected words, weakest first, as the hints file spells them.
RARE_CAPITAL = "capital in mid-sentence, rare"
ONE_READING = "one reading differs"
INNER_CAPS = "capital letter inside the word"
DIGIT = "digit inside the word"
UNKNOWN = "not in dictionary"
TWO_READINGS = "two readings disagree"
LATIN = "Latin letters"


# ------------------------------------------------------------------ helpers


def make_page(
    lines, page=110, *, width=200, height=300, source=None, flags=None, line_left=None, header=None
):
    """A page in the shape of C2, built from line texts. Every word is 30 page pixels high on a
    line 60 pixels below the previous one. Lines start 30 pixels from the left edge, or 130 when
    they are paragraph starts (`line_left`). An optional running title comes first, as a header."""
    page_lines = []
    for index, text in enumerate([header, *lines] if header else lines):
        is_header = header is not None and index == 0
        number = index - (1 if header else 0)
        top = 10 if is_header else 40 + 60 * number
        left = 130 if not is_header and line_left and number in line_left else 30
        words = []
        for word_text in text.split(" "):
            words.append(
                {
                    "text": word_text,
                    "left": left,
                    "top": top,
                    "width": 8 * len(word_text),
                    "height": 30,
                    "conf": 90.0,
                    "red": 0.0,
                    "color": "black",
                    "flags": (flags or {}).get(word_text, []),
                }
            )
            left += 8 * len(word_text) + 8
        page_lines.append(
            {
                "kind": "header" if is_header else "content",
                "cy": top + 15,
                "top": top - 5,
                "bottom": top + 35,
                "left": words[0]["left"],
                "right": words[-1]["left"] + words[-1]["width"],
                "text": text,
                "words": words,
            }
        )
    data = {"page": page, "book_page": page + 3, "width": width, "height": height, "lines": page_lines}
    if source:
        data["source_width"], data["source_height"] = source
    return data


def put_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def suspected(path: Path) -> list[str]:
    """The `NN "word" (reason)` lines of a hints file; empty when the page has none."""
    text = path.read_text(encoding="utf-8")
    return text.split("Suspected words:\n")[1].splitlines() if "Suspected words:\n" in text else []


def draw_scan(path: Path, page: dict, size=None) -> Path:
    """A white scan with a dark bar where every word box of `page` is (two scan pixels per page
    pixel), saved under `path` in the format of its extension."""
    image = Image.new("RGB", size or (page["source_width"], page["source_height"]), "white")
    for line in page["lines"]:
        for word in line["words"]:
            image.paste(
                (40, 40, 40),
                (
                    2 * word["left"],
                    2 * word["top"],
                    2 * (word["left"] + word["width"]),
                    2 * (word["top"] + word["height"]),
                ),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def is_ink(pixel) -> bool:
    return max(pixel) < 128


def is_tinted(pixel) -> bool:
    red, green, blue = pixel
    return red > 250 and green > 235 and blue < 225


def pixels_of(image: Image.Image) -> list[tuple[int, int, int]]:
    """The pixels of an RGB image, row by row."""
    raw = image.tobytes()
    return [tuple(raw[n : n + 3]) for n in range(0, len(raw), 3)]


def row_bands(image: Image.Image, is_pixel, least=20) -> list[tuple[int, int]]:
    """First and last row of every run of rows on which at least `least` pixels satisfy `is_pixel`."""
    pixels = pixels_of(image)
    rows = [
        y
        for y in range(image.height)
        if sum(is_pixel(p) for p in pixels[y * image.width : (y + 1) * image.width]) >= least
    ]
    bands = []
    for y in rows:
        if bands and y == bands[-1][1] + 1:
            bands[-1][1] = y
        else:
            bands.append([y, y])
    return [(first, last) for first, last in bands]


def centre(band: tuple[int, int]) -> float:
    return (band[0] + band[1]) / 2


def ink_spread(image: Image.Image) -> tuple[int, int]:
    """The first and the last column of `image` that has ink."""
    columns = [n % image.width for n, pixel in enumerate(pixels_of(image)) if is_ink(pixel)]
    return min(columns), max(columns)


def cli(root: Path, *argv: str) -> int:
    """Run the step on its command line, with `root` as the repository."""
    return review.main(["--root", str(root), *argv])


def parse(argv: list[str]):
    """Parse `molitvenik review <argv…>` the way the CLI does, without running it."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="step", required=True)
    review.add_parser(subparsers)
    return parser.parse_args(["review", *argv])


def strip_root(tmp_path: Path, marked: dict, second=None, *, source=(400, 600), name="p-110.png"):
    """A repository with one OCR page of three lines over a 400 x 600 scan, its marked lines and
    optionally its second reading. Returns the page."""
    page = make_page(["прва линија", "друга линија", "трећа линија"], source=source)
    put_json(tmp_path / "build/ocr/p-110.json", page)
    put_json(tmp_path / "build/review/marked.json", marked)
    if second is not None:
        put_json(tmp_path / "build/ia-ocr/p-110.json", {"page": 110, "lines": second})
    draw_scan(tmp_path / "build/pages" / name, page, size=(400, 600))
    return page


def corrections_root(tmp_path: Path) -> Path:
    """A repository with two OCR pages and an empty directory of corrections."""
    put_json(
        tmp_path / "build/ocr/p-110.json",
        make_page(["бедни учествујем у Твојој бо-", "жанској Вечери Тајној.", "Песма 5."], page=110),
    )
    put_json(
        tmp_path / "build/ocr/p-127.json",
        make_page(["даје неправедним судијама.", "свидбени судијама.", "Амин.", "Амин."], page=127),
    )
    out = tmp_path / "corrections"
    out.mkdir()
    return out


# -------------------------------------------------------------------- hints


def test_hints_list_the_suspected_words_by_priority(tmp_path, capsys):
    page = make_page(
        [
            "према свима Добри, слава",  # the weakest reason on the first line, the strongest last
            "тада се жени и погледај",
            "страда ГосСПОДе тихо",
            "страшно утробе7 и остало",
            "сачувај мене, слугу твог, неисказано",
            "жни болујући, страда од сре-",
            "за време Beuepe умивањем",
        ],
        flags={
            "погледај": ["differs:scale50-p6"],
            "ГосСПОДе": ["has-inner-caps"],
            "болујући,": ["differs:scale40-p3", "differs:scale50-p6"],
            "Beuepe": ["latin-letters"],
        },
    )
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown={"неисказано"})

    assert path == tmp_path / "build/review/hints/p-110.txt"
    assert path.read_text(encoding="utf-8").splitlines() == [
        "PDF page 110 (book page 113). 7 content lines.",
        "01| према свима Добри, слава",
        "02| тада се жени и погледај",
        "03| страда ГосСПОДе тихо",
        "04| страшно утробе7 и остало",
        "05| сачувај мене, слугу твог, неисказано",
        "06| жни болујући, страда од сре-",
        "07| за време Beuepe умивањем",
        "Suspected words:",
        f'07 "Beuepe" ({LATIN})',
        f'06 "болујући," ({TWO_READINGS})',
        f'05 "неисказано" ({UNKNOWN})',
        f'04 "утробе7" ({DIGIT})',
        f'03 "ГосСПОДе" ({INNER_CAPS})',
        f'02 "погледај" ({ONE_READING})',
        f'01 "Добри," ({RARE_CAPITAL})',
    ]
    assert "pages=1 words=30 hinted_words=7" in capsys.readouterr().out


def test_latin_tokens_are_listed_first(tmp_path):
    # The first review of the real page 127 had „Вечере" read as Latin „Beuepe".
    page = make_page(
        ["када се славни ученици", "за време Beuepe умивањем", "жни болујући, страда од сре-"],
        page=127,
        flags={"Beuepe": ["latin-letters"], "болујући,": ["differs:scale50-p6"]},
    )
    put_json(tmp_path / "build/ocr/p-127.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown=set())

    assert suspected(path) == [f'02 "Beuepe" ({LATIN})', f'03 "болујући," ({ONE_READING})']


def test_an_allowlisted_word_is_not_reported_as_unknown(tmp_path):
    page = make_page(["богородице дево радуј се", "слугу твог неисказано данас"])
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, {"богородице"}, None, unknown={"богородице", "неисказано"})

    assert suspected(path) == [f'02 "неисказано" ({UNKNOWN})']


def test_the_continuation_of_a_hyphenated_word_is_not_looked_up(tmp_path):
    page = make_page(["исцели господе ране ду-", "ше моје и освети ме целог"])
    put_json(tmp_path / "build/ocr/p-110.json", page)

    # „ше" alone is not a word: only the joined „душе" and the stem „ду" are asked about.
    (path,) = review.write_hints(tmp_path, set(), None, unknown={"ше", "душе"})
    assert suspected(path) == []

    (path,) = review.write_hints(tmp_path, set(), None, unknown={"ше", "душе", "ду"})
    assert suspected(path) == [f'01 "ду-" ({UNKNOWN})']


def test_at_most_45_hints_are_listed(tmp_path, capsys):
    letters = "абвгдежзиклмнопрстуфхц"
    words = [f"реч{letters[i // 20]}{letters[i % 20]}ник" for i in range(60)]
    page = make_page([" ".join(words[n : n + 20]) for n in (0, 20, 40)])
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown=set(words))

    listed = suspected(path)
    assert len(listed) == 45
    assert listed[0] == f'01 "{words[0]}" ({UNKNOWN})'
    assert listed[19] == f'01 "{words[19]}" ({UNKNOWN})'
    assert listed[20] == f'02 "{words[20]}" ({UNKNOWN})'
    assert listed[44] == f'03 "{words[44]}" ({UNKNOWN})'
    assert "hinted_words=45" in capsys.readouterr().out


def test_tokens_with_fewer_than_two_letters_are_not_listed(tmp_path):
    # … unless a digit stands next to the letter: „ч0-" is a word whose „о" was read as a
    # digit; and a number on which another reading differs is listed too.
    page = make_page(
        ["исцели господе ране ч0-", "ше моје 60- и освети ме целог"],
        flags={"60-": ["differs:scale50-p6"], "и": ["latin-letters"]},
    )
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown={"и", "60-", "ше"})

    assert suspected(path) == [f'01 "ч0-" ({DIGIT})', f'02 "60-" ({ONE_READING})']


@pytest.mark.parametrize("indented, expected", [(True, []), (False, [f'02 "Нова" ({RARE_CAPITAL})'])])
def test_only_a_capital_inside_a_sentence_is_suspected(tmp_path, indented, expected):
    # the first word of a page and a word after a full stop start a sentence
    page = make_page(
        ["Прва реченица овде. Друга следи", "Нова реченица почиње овде"], line_left={1} if indented else None
    )
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown=set())

    assert suspected(path) == expected


@pytest.mark.parametrize("times, hints", [(2, 2), (3, 0)])
def test_a_capital_that_is_frequent_in_mid_sentence_is_not_suspected(tmp_path, times, hints):
    ordinals = ("прве", "друге", "треће")
    page = make_page([f"речи {ordinals[n]} Реченице стоје" for n in range(times)])
    put_json(tmp_path / "build/ocr/p-110.json", page)

    (path,) = review.write_hints(tmp_path, set(), None, unknown=set())

    assert [line for line in suspected(path) if RARE_CAPITAL in line] == [
        f'{n + 1:02d} "Реченице" ({RARE_CAPITAL})' for n in range(hints)
    ]


def test_hints_of_a_real_page(fixtures, tmp_path, capsys):
    page = load(fixtures / "ocr" / "p-127.json")
    put_json(tmp_path / "build/ocr/p-127.json", page)

    (path,) = review.write_hints(tmp_path, review.load_allowlist(REPO), None, unknown=set())

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "PDF page 127 (book page 130). 23 content lines."
    assert lines[1] == "01| У току свете и велике Четрдесетнице,"
    assert lines[23] == "23| је огањ."
    assert lines[24] == "Suspected words:"
    assert lines[25:] == [
        f'17 "ГосСПОДе" ({INNER_CAPS})',
        f'17 "ПОМИЛУЈ!" ({INNER_CAPS})',
        f'07 "брољубља," ({ONE_READING})',
        f'09 "даје" ({ONE_READING})',
        f'09 "неправедним" ({ONE_READING})',
        f'10 "погледај" ({ONE_READING})',
        f'14 "Према" ({ONE_READING})',
        f'16 "Ти." ({ONE_READING})',
        f'17 "пута" ({ONE_READING})',
        f'20 "једеш" ({ONE_READING})',
        f'23 "огањ." ({ONE_READING})',
        f'04 "Вечере" ({RARE_CAPITAL})',
        f'08 "Тебе," ({RARE_CAPITAL})',
        f'08 "Судију," ({RARE_CAPITAL})',
        f'14 "Учитељем." ({RARE_CAPITAL})',
        f'15 "Господе," ({RARE_CAPITAL})',
        f'21 "Тело" ({RARE_CAPITAL})',
        f'21 "Господње," ({RARE_CAPITAL})',
    ]
    # „Јуда" is on the allowlist, and a single letter is never a hint although a reading differs.
    assert not any("Јуда" in line or '"и"' in line for line in lines[25:])
    assert "pages=1 words=96 hinted_words=18" in capsys.readouterr().out


def test_without_hunspell_the_dictionary_reasons_are_skipped_and_that_is_said(tmp_path, capsys, monkeypatch):
    page = make_page(["слугу твог неисказано данас"])
    put_json(tmp_path / "build/ocr/p-110.json", page)
    monkeypatch.setattr(review, "unknown_words", lambda forms, base: None)

    (path,) = review.write_hints(tmp_path, set(), "/path/to/sr")

    assert suspected(path) == []
    assert "hunspell" in capsys.readouterr().out

    review.write_hints(tmp_path, set(), None)
    assert "--hunspell" in capsys.readouterr().out


def test_a_missing_hunspell_binary_is_not_an_error():
    assert review.unknown_words({"реч"}, "/path/to/sr", binary="no-such-hunspell") is None


def test_hunspell_is_called_once_per_run_with_every_form(tmp_path, monkeypatch):
    pages = [
        make_page(["исцели господе ране ду-", "ше моје и освети ме целог"], page=110),
        make_page(["жанској Вечери Тајној."], page=127),
    ]
    for page in pages:
        put_json(tmp_path / f"build/ocr/p-{page['page']:03d}.json", page)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["input"]))
        return subprocess.CompletedProcess(command, 0, stdout="вечери\n", stderr="")

    monkeypatch.setattr(review.subprocess, "run", fake_run)

    paths = review.write_hints(tmp_path, set(), "/dict/sr")

    assert [path.name for path in paths] == ["p-110.txt", "p-127.txt"]
    assert len(calls) == 1
    command, stdin = calls[0]
    assert command == ["hunspell", "-d", "/dict/sr", "-l", "-i", "UTF-8"]
    # „душе" is „ду-" joined with what follows it; „ше" is not a word of its own; „и" is one letter
    assert (
        stdin
        == "\n".join(
            sorted(
                [
                    "исцели",
                    "господе",
                    "ране",
                    "душе",
                    "ду",
                    "моје",
                    "освети",
                    "ме",
                    "целог",
                    "жанској",
                    "вечери",
                    "тајној",
                ]
            )
        )
        + "\n"
    )


def test_hints_command_writes_one_file_per_page(tmp_path, capsys):
    for number in (110, 127):
        put_json(
            tmp_path / f"build/ocr/p-{number:03d}.json", make_page(["ше моје и освети ме целог"], page=number)
        )
    (tmp_path / "data").mkdir()
    (tmp_path / "data/lexicon-allowlist.txt").write_text("целог\n", encoding="utf-8")

    assert cli(tmp_path, "hints") == 0

    assert (tmp_path / "build/review/hints/p-110.txt").exists()
    assert (tmp_path / "build/review/hints/p-127.txt").exists()
    assert "pages=2" in capsys.readouterr().out


def test_hints_need_the_allowlist_and_the_pages(tmp_path, capsys):
    assert cli(tmp_path, "hints") == 2
    assert "lexicon-allowlist.txt" in capsys.readouterr().err

    (tmp_path / "data").mkdir()
    (tmp_path / "data/lexicon-allowlist.txt").write_text("", encoding="utf-8")
    assert cli(tmp_path, "hints") == 2
    assert "build/ocr" in capsys.readouterr().err


# ------------------------------------------------------------ marked lines


def test_a_second_reading_with_one_changed_word_marks_that_line():
    page = make_page(["исцели господе ране ду-", "ше моје и освети ме целог"])
    second = ["исцели господе ране ду-", "ше моје и освети те целог"]

    assert review.marked_lines(page, second, set()) == [1]
    assert review.diff_against(page, second) == [
        {
            "page": 110,
            "line_index": 1,
            "line": "ше моје и освети ме целог",
            "other": "ше моје и освети те целог",
            "diffs": [{"ours": ["ме"], "theirs": ["те"]}],
        },
    ]


def test_the_running_title_and_the_page_number_of_the_second_reading_are_not_its_extra_lines():
    page = make_page(
        ["исцели господе ране ду-", "ше моје и освети ме целог"],
        header="Молитвено правило пред Свето причешће",
    )
    second = [
        "молитвено правило пред свето причешће",
        "исцели господе ране ду-",
        "ше моје и освети ме целог",
        "113",
    ]

    assert review.diff_against(page, second) == []
    assert review.marked_lines(page, second, set()) == []


def test_the_page_number_read_into_a_line_of_marks_is_not_an_extra_line():
    """The Archive's OCR often glues the page number to marks and stray letters."""
    page = make_page(["исцели господе ране ду-", "Кондак 1"], header="Молитвено правило пред Свето причешће")
    last = page["lines"][-1]
    page["lines"].append(
        {
            **last,
            "kind": "footer",
            "cy": 295,
            "top": 285,
            "bottom": 315,
            "text": "113",
            "words": [{**last["words"][0], "text": "113", "left": 30, "width": 24, "top": 290}],
        }
    )
    second = [
        "Молитвено правило пред Свето причешће",
        "исцели господе ране ду-",
        "Кондак 1",
        "113 сы пп аат ====",
    ]

    assert review.diff_against(page, second) == []
    assert review.diff_against(page, second[:-1] + ["амин."])[-1]["only_other"] is True
    # „Кондак 1" is a line with a number in it, not a page number
    assert review.marked_lines(page, second[:-1], set()) == []
    assert review.marked_lines(page, second[:-2] + ["Кондак 11"], set()) == [2]


def test_a_line_that_only_the_other_reading_has_is_reported_against_our_line_before_it():
    """A printed line that our OCR does not have at all is the worst error there is, and it
    shows only in the other reading."""
    page = make_page(["исцели господе ране ду-", "ше моје и освети ме целог"])
    in_the_middle = ["исцели господе ране ду-", "о милосрђу божјем", "ше моје и освети ме целог"]

    assert review.diff_against(page, in_the_middle) == [
        {
            "page": 110,
            "line_index": 0,
            "line": "исцели господе ране ду-",
            "other": "о милосрђу божјем",
            "diffs": [{"ours": [], "theirs": ["о", "милосрђу", "божјем"]}],
            "extra": ["о милосрђу божјем"],
            "only_other": True,
        }
    ]
    at_the_end = ["исцели господе ране ду-", "ше моје и освети ме целог", "амин."]
    assert [entry["line_index"] for entry in review.diff_against(page, at_the_end)] == [1]
    assert review.marked_lines(page, at_the_end, set()) == [1]


def test_a_line_that_only_the_other_reading_has_is_found_beside_a_line_that_differs():
    """The lost line and a misread word on its neighbour land in one block of lines; the lost
    line must not drown in the word-by-word comparison."""
    page = make_page(["исцели господе ране ду-", "ше моје и освети ме целог"])
    second = ["исцели господе ране ду-", "о милосрђу божјем", "ше моје и освети те целог"]

    assert review.diff_against(page, second) == [
        {
            "page": 110,
            "line_index": 0,
            "line": "исцели господе ране ду-",
            "other": "о милосрђу божјем",
            "diffs": [{"ours": [], "theirs": ["о", "милосрђу", "божјем"]}],
            "extra": ["о милосрђу божјем"],
            "only_other": True,
        },
        {
            "page": 110,
            "line_index": 1,
            "line": "ше моје и освети ме целог",
            "other": "ше моје и освети те целог",
            "diffs": [{"ours": ["ме"], "theirs": ["те"]}],
        },
    ]
    # after the line that differs: both of the other reading's lines are named, in reading order
    second = ["исцели господе ране ду-", "ше моје и освети те целог", "о милосрђу божјем"]
    (entry,) = review.diff_against(page, second)
    assert entry["line_index"] == 1
    assert (
        "extra" not in review.diff_against(page, ["исцели господе ране ду-", "ше моје и освети те целог"])[0]
    )
    assert entry["other"] == review.OTHER.join(["ше моје и освети те целог", "о милосрђу божјем"])
    assert entry["diffs"] == [
        {"ours": ["ме"], "theirs": ["те"]},
        {"ours": [], "theirs": ["о", "милосрђу", "божјем"]},
    ]
    assert entry["extra"] == ["о милосрђу божјем"]
    assert "only_other" not in entry  # the other reading has a word of ours here as well
    assert review.marked_lines(page, second, set()) == [1]


@pytest.mark.parametrize(
    "book_page, last",
    [
        (20, "ааа 20 (етен"),
        (55, "Е 30 —————"),
        (84, "мн 184"),
        (86, "а ~ 36"),
        (158, "Е ЧЕЧЕ ЧЕ Е Бае. ИС. НЕН 158 ааа аан а о 8."),
    ],
)
def test_the_page_number_misread_or_glued_to_many_words_is_not_an_extra_line(book_page, last):
    """What the Archive's OCR made of the page number on five pages of this book."""
    page = make_page(["исцели господе ране ду-", "Кондак 1"])
    page["book_page"] = book_page
    second = ["исцели господе ране ду-", "Кондак 1", last]

    assert review.diff_against(page, second) == []
    assert review.marked_lines(page, second, set()) == []
    # a last line that carries a number and a word of our text is a line, not the page number
    assert review.marked_lines(page, second[:-1] + ["Кондак 11"], set()) == [1]


def test_a_number_that_differs_is_a_disagreement():
    page = make_page(["Кондак 1", "Теби војводо који се бориш"])

    assert review.marked_lines(page, ["Кондак 11", "Теби војводо који се бориш"], set()) == [0]
    assert review.marked_lines(page, ["Кондак 1", "Теби војводо који се бориш"], set()) == []
    # punctuation counts, as with any other word
    assert review.marked_lines(page, ["Кондак 1:", "Теби војводо који се бориш"], set()) == [0]


def test_a_number_on_which_another_reading_differs_is_hinted():
    page = make_page(
        ["Кондак 1", "Теби војводо"], flags={"1": ["differs:psm6"], "војводо": []}, line_left={1}
    )

    assert [(hint.word, hint.reason) for hint in review.suspected_words([page], set(), set())] == [
        ("1", "one reading differs")
    ]


@pytest.mark.parametrize(
    "second", [["ГОСПОДЕ помилуј нас."], ["Господе помилуј нас!"], ["господе помилуј нас."]]
)
def test_a_difference_of_letter_case_or_punctuation_marks_the_line(second):
    page = make_page(["Господе помилуј нас."])

    assert review.marked_lines(page, second, set()) == [0]


def test_a_run_of_more_than_two_tokens_marks_nothing():
    page = make_page(["тмене покрива земљу данас ноћу"])

    assert review.marked_lines(page, ["сунце обасјава планине јутрос ведро"], set()) == []
    assert review.marked_lines(page, ["тмене покрива земљу јутрос ведро"], set()) == [0]


def test_symbols_without_letters_do_not_count():
    page = make_page(["примивши ~ духовни ~ бисер,"])

    assert review.marked_lines(page, ["примивши духовни бисер,"], set()) == []


def test_latin_letters_that_look_like_cyrillic_ones_are_the_same_word():
    page = make_page(["говори овај море тропар:"])

    assert review.marked_lines(page, ["говори овај mope тропар:"], set()) == []


def test_other_line_breaks_of_the_second_reading_do_not_mark_a_line():
    page = make_page(["у току свете и велике четрдесетнице,", "говори овај тропар:"])
    second = ["у току свете и велике", "четрдесетнице, говори овај тропар:"]

    assert review.marked_lines(page, second, set()) == []


def test_marked_lines_combine_hints_and_disagreement():
    page = make_page(
        ["ше моје и освети ме целог", "исцели господе ране ду-"],
        header="Молитвено правило пред Свето причешће",
    )
    second = ["ше моје и освети те целог", "исцели господе ране ду-"]

    # indexes are into all the lines of the page: the content lines are 1 and 2
    assert review.marked_lines(page, second, {2}) == [1, 2]
    assert review.marked_lines(page, second, set()) == [1]
    # a line of four words that the second reading does not have is not a small disagreement
    assert review.marked_lines(page, second[:1], set()) == [1]


def test_low_confidence_alone_does_not_mark_a_line(tmp_path):
    page = make_page(["ше моје и освети ме целог"], flags={"освети": ["low-confidence"]})
    put_json(tmp_path / "build/ocr/p-110.json", page)

    marked = review.write_marked(tmp_path, set(), None, unknown=set())

    assert marked == {"110": []}
    assert load(tmp_path / "build/review/marked.json") == marked


def test_the_real_second_reading_disagrees_on_three_lines_of_page_110(fixtures):
    page = load(fixtures / "ocr" / "p-110.json")

    entries = review.diff_against(page, load(fixtures / "ia-ocr" / "p-110.json")["lines"])

    # „бо-" against „60-", and small capitals read in sentence case
    assert [(entry["line_index"], entry["diffs"]) for entry in entries] == [
        (4, [{"ours": ["бо-"], "theirs": ["60-"]}]),
        (6, [{"ours": ["Умилостиви,"], "theirs": ["УМИЛОСТИВИ,"]}]),
        (15, [{"ours": ["води"], "theirs": ["ВОДИ"]}]),
    ]
    assert entries[0]["other"] == "бедни учествујем у Твојој 60-"
    assert review.marked_lines(page, load(fixtures / "ia-ocr" / "p-110.json")["lines"], set()) == [4, 6, 15]


@pytest.mark.parametrize(
    "kind, name", [("transcription", "p-110"), ("transcription", "p-137"), ("ia-ocr", "p-137")]
)
def test_the_real_readings_that_agree_with_the_ocr(fixtures, kind, name):
    page = load(fixtures / "ocr" / f"{name}.json")

    assert review.diff_against(page, load(fixtures / kind / f"{name}.json")["lines"]) == []


def test_marked_command_writes_marked_json(tmp_path, capsys):
    put_json(
        tmp_path / "build/ocr/p-110.json", make_page(["пасха господња"], page=110, header="Молитвено правило")
    )
    put_json(
        tmp_path / "build/ia-ocr/p-110.json", {"page": 110, "lines": ["молитвено правило", "пасха господња"]}
    )
    put_json(
        tmp_path / "build/ocr/p-127.json",
        make_page(["пасха господња"], page=127, flags={"пасха": ["latin-letters"]}),
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data/lexicon-allowlist.txt").write_text("", encoding="utf-8")

    assert cli(tmp_path, "marked") == 0

    # the running title is a header for our OCR and an extra line for the Archive's
    assert load(tmp_path / "build/review/marked.json") == {"110": [], "127": [0]}
    out = capsys.readouterr().out
    assert "no second reading for pages: 127" in out
    assert "--hunspell" in out


# ------------------------------------------------------------------- strips


@pytest.mark.parametrize("source", [(400, 600), None], ids=["with-source-size", "without"])
def test_a_strip_shows_the_marked_line_tinted_with_its_neighbours_whole(tmp_path, source):
    strip_root(tmp_path, {"110": [1]}, source=source)

    (path,) = review.write_strips(tmp_path, [110])

    assert path == tmp_path / "build/review/strips/p-110-1.png"
    image = Image.open(path).convert("RGB")
    ink = row_bands(image, is_ink)
    tint = row_bands(image, is_tinted)
    assert len(ink) == 3, "the marked line and the lines above and below it"
    assert ink[0][0] > 0 and ink[2][1] < image.height - 1, "the neighbours are whole"
    assert len(tint) == 1
    assert abs(centre(tint[0]) - centre(ink[1])) <= 3, "the tint sits on the marked line"
    assert tint[0][0] > ink[0][1] and tint[0][1] < ink[2][0], "and on neither neighbour"
    # shown at 0.72 of the scan: the words of the widest line span 96 page pixels = 192 scan
    # pixels, and the centres of two neighbouring lines are 60 page pixels = 120 scan pixels apart
    first, last = ink_spread(image)
    assert last - first + 1 == round(192 * 0.72)
    assert abs(centre(ink[1]) - centre(ink[0]) - 120 * 0.72) <= 2
    assert ink_spread(image)[0] > 0, "there is room for the label on the left"


def test_strips_that_fit_go_into_one_image_named_1(tmp_path, capsys):
    strip_root(tmp_path, {"110": [0, 2]})

    (path,) = review.write_strips(tmp_path, [110])

    assert path.name == "p-110-1.png"
    image = Image.open(path).convert("RGB")
    tint = row_bands(image, is_tinted)
    ink = row_bands(image, is_ink)
    assert len(tint) == 2
    assert len(ink) == 4, "two strips, each with the marked line and one neighbour"
    assert abs(centre(tint[0]) - centre(ink[0])) <= 3
    assert abs(centre(tint[1]) - centre(ink[3])) <= 3
    assert "p-110: 2 strips in 1 image" in capsys.readouterr().out


def test_strips_that_do_not_fit_one_image_are_split_between_strips(tmp_path, capsys):
    names = ["прва", "друга", "трећа", "четврта", "пета", "шеста", "седма", "осма", "девета", "десета"]
    page = make_page([f"{name} линија текста" for name in names], height=700, source=(400, 1400))
    put_json(tmp_path / "build/ocr/p-110.json", page)
    put_json(tmp_path / "build/review/marked.json", {"110": list(range(10))})
    draw_scan(tmp_path / "build/pages/p-110.png", page)
    stale = put_json(tmp_path / "build/review/strips/p-110.png", {})  # the name of a first run

    written = review.write_strips(tmp_path, [110])

    assert [path.name for path in written] == ["p-110-1.png", "p-110-2.png"]
    first = Image.open(written[0]).convert("RGB")
    second = Image.open(written[1]).convert("RGB")
    assert first.height <= 1800 and second.height <= 1800
    # a strip of an inner line is 242 pixels high and the gap 14: no more would have fitted
    assert first.height + 242 + 14 > 1800
    text = (tmp_path / "build/review/strips/p-110.txt").read_text(encoding="utf-8").splitlines()
    assert text[1] == "Images: p-110-1.png (strips 1–7), p-110-2.png (strips 8–10)."
    assert [line.split(" A: ")[0] for line in text if "| [" in line] == [
        f"{n:02d}| [p-110-{1 if n <= 7 else 2}.png]" for n in range(1, 11)
    ]
    # each image shows the strips whose notes name it: one tinted band per strip
    assert len(row_bands(first, is_tinted)) == 7
    assert len(row_bands(second, is_tinted)) == 3
    assert "p-110: 10 strips in 2 images" in capsys.readouterr().out
    assert not stale.exists(), "the image of the earlier run is gone"


def test_images_of_an_earlier_run_are_replaced(tmp_path):
    page = make_page(["прва линија", "друга линија", "трећа линија"], source=(400, 600))
    put_json(tmp_path / "build/ocr/p-110.json", page)
    put_json(tmp_path / "build/review/marked.json", {"110": [0, 1, 2]})
    draw_scan(tmp_path / "build/pages/p-110.png", page)
    for name in ("p-110-1.png", "p-110-2.png", "p-110-3.png"):
        put_json(tmp_path / "build/review/strips" / name, {})
    put_json(tmp_path / "build/review/strips/p-111-2.png", {})

    assert [path.name for path in review.write_strips(tmp_path, [110])] == ["p-110-1.png"]

    assert sorted(p.name for p in (tmp_path / "build/review/strips").iterdir()) == [
        "p-110-1.png",
        "p-110.txt",
        "p-111-2.png",
    ], "only this page's images are replaced"


def test_the_strips_text_lists_each_marked_line_and_how_the_readings_differ(tmp_path):
    strip_root(tmp_path, {"110": [0, 1]}, second=["прва линија", "друга линија слова", "трећа линија"])

    (path,) = review.write_strips(tmp_path, [110])

    text = (tmp_path / "build/review/strips/p-110.txt").read_text(encoding="utf-8").splitlines()
    assert text[1] == "Images: p-110-1.png (strips 1–2)."
    assert [line for line in text if line[:1].isdigit() and "| [" in line] == [
        "01| [p-110-1.png] A: прва линија",
        "02| [p-110-1.png] A: друга линија",
    ]
    assert text[text.index("02| [p-110-1.png] A: друга линија") + 1 :] == [
        "    B: друга линија слова",
        "    differs: A [—] / B [слова]",
    ]
    assert text[0].startswith("PDF page 110 (book page 113).")


def test_strips_also_cut_the_archive_page_image(tmp_path):
    strip_root(tmp_path, {"110": [1]}, name="n109_w2000.jpg")

    (path,) = review.write_strips(tmp_path, [110])

    assert Image.open(path).width > 64


def test_a_scan_of_another_size_than_the_ocr_read_is_refused(tmp_path):
    page = strip_root(tmp_path, {"110": [1]})
    draw_scan(tmp_path / "build/pages/p-110.png", page, size=(300, 450))

    with pytest.raises(review.ReviewError, match="300x450.*400x600"):
        review.write_strips(tmp_path, [110])


def test_strips_need_marked_lines(tmp_path, capsys):
    assert cli(tmp_path, "strips") == 2
    assert "marked.json" in capsys.readouterr().err

    strip_root(tmp_path, {"110": []})
    assert cli(tmp_path, "strips", "--pages", "110,127") == 0
    assert "no marked lines" in capsys.readouterr().out
    assert not (tmp_path / "build/review/strips").exists()


# --------------------------------------------------------------------- diff


def test_diff_command_compares_transcriptions_and_tells_what_was_marked_before(tmp_path, capsys):
    page = make_page(["исцели господе ране ду-", "ше моје и освети ме целог", "Песма 5."])
    put_json(tmp_path / "build/ocr/p-110.json", page)
    put_json(tmp_path / "build/review/marked.json", {"110": [0]})
    put_json(
        tmp_path / "transcriptions/p-110.json",
        {"page": 110, "lines": ["исцели господе ране бо-", "ше моје и освети те целог", "Песма 5."]},
    )
    put_json(tmp_path / "build/ocr/p-111.json", make_page(["пасха господња"], page=111))
    put_json(tmp_path / "transcriptions/p-111.json", {"page": 111, "lines": ["пасха"]})

    assert cli(tmp_path, "diff", "--transcriptions", str(tmp_path / "transcriptions")) == 0

    entries = load(tmp_path / "build/review/diff.json")
    assert [(entry["page"], entry["line_index"], entry["marked_before"]) for entry in entries] == [
        (110, 0, True),
        (110, 1, False),
        (111, 0, False),
    ]
    assert entries[0]["diffs"] == [{"ours": ["ду-"], "theirs": ["бо-"]}]
    out = capsys.readouterr().out
    assert "with_disagreement=3" in out and "marked before: 1" in out and "not marked: 2" in out


def test_diff_without_marked_json_leaves_the_lines_unclassified(tmp_path, capsys):
    put_json(tmp_path / "build/ocr/p-110.json", make_page(["исцели господе ране ду-"]))
    put_json(tmp_path / "transcriptions/p-110.json", {"page": 110, "lines": ["исцели господе ране бо-"]})

    assert cli(tmp_path, "diff", "--transcriptions", str(tmp_path / "transcriptions")) == 0

    assert load(tmp_path / "build/review/diff.json")[0]["marked_before"] is None
    assert "marked.json" in capsys.readouterr().out


def test_a_transcription_without_ocr_page_is_an_error(tmp_path, capsys):
    put_json(tmp_path / "transcriptions/p-110.json", {"page": 110, "lines": []})

    assert cli(tmp_path, "diff", "--transcriptions", str(tmp_path / "transcriptions")) == 2
    assert "page 110" in capsys.readouterr().err


# ----------------------------------------------------------------- collect


def test_collect_rejects_a_line_a_find_or_a_change_that_does_not_fit(tmp_path):
    out = corrections_root(tmp_path)
    put_json(
        out / "p-110.json",
        {
            "page": 110,
            "corrections": [
                {"line": "бедни учествујем у Твоју бо-", "find": "бо-", "replace": "жи-"},
                {"line": "бедни учествујем у Твојој бо-", "find": "Твоју", "replace": "Твоје"},
                {"line": "жанској Вечери Тајној.", "find": "Вечери Тајној", "replace": "Твојој светињи"},
                {"line": "Песма 5.", "find": 5, "replace": "6"},
            ],
        },
    )
    put_json(
        out / "p-127.json",
        {
            "page": 127,
            "corrections": [
                {"line": "Амин.", "find": "Амин.", "replace": "Амин!"},
                {"line": "даје неправедним судијама.", "find": "е", "replace": "и"},
                {"line": "даје неправедним судијама.", "find": "судијама.", "replace": "судијама."},
            ],
        },
    )

    result = review.collect(tmp_path, out)

    assert result["valid"] == []
    assert [(entry["file"], entry["index"], entry["reason"]) for entry in result["invalid"]] == [
        ("p-110.json", 0, "line matched 0 times"),
        ("p-110.json", 1, "find occurs 0 times in line"),
        ("p-110.json", 2, "too large a change"),
        ("p-110.json", 3, "missing or non-string field"),
        ("p-127.json", 0, "line matched 2 times"),
        ("p-127.json", 1, "find occurs 3 times in line"),
        ("p-127.json", 2, "no change"),
    ]
    assert result["invalid"][0]["line"] == "бедни учествујем у Твоју бо-"


def test_collect_rejects_a_correction_that_overlaps_another_one_on_its_line(tmp_path):
    out = corrections_root(tmp_path)
    put_json(
        out / "p-110.json",
        {
            "page": 110,
            "corrections": [
                {"line": "бедни учествујем у Твојој бо-", "find": "бедни", "replace": "гладан"},
                {"line": "бедни учествујем у Твојој бо-", "find": "едни", "replace": "адан"},
            ],
        },
    )

    result = review.collect(tmp_path, out)

    assert [entry["find"] for entry in result["valid"]] == ["бедни"]
    assert [(entry["index"], entry["reason"]) for entry in result["invalid"]] == [
        (1, "overlaps another correction on the line"),
    ]


def test_collect_keeps_two_corrections_of_one_line_and_sorts_by_page_and_line(tmp_path):
    out = corrections_root(tmp_path)
    put_json(
        out / "z-page.json",
        {
            "page": 127,
            "corrections": [
                {"line": "свидбени судијама.", "find": "свидбени", "replace": "свидебени"},
            ],
        },
    )
    put_json(
        out / "a-page.json",
        {
            "page": 110,
            "corrections": [
                {"line": "Песма 5.", "find": "Песма", "replace": "Ирмос"},
                {
                    "line": "бедни учествујем у Твојој бо-",
                    "find": "Твојој",
                    "replace": "твојој",
                    "note": "printed in lower case",
                },
                {"line": "бедни учествујем у Твојој бо-", "find": "бедни", "replace": "гладан"},
            ],
        },
    )

    result = review.collect(tmp_path, out)

    assert result["invalid"] == []
    assert result["valid"] == [
        {
            "page": 110,
            "line": "бедни учествујем у Твојој бо-",
            "find": "Твојој",
            "replace": "твојој",
            "note": "printed in lower case",
        },
        {
            "page": 110,
            "line": "бедни учествујем у Твојој бо-",
            "find": "бедни",
            "replace": "гладан",
            "note": "",
        },
        {"page": 110, "line": "Песма 5.", "find": "Песма", "replace": "Ирмос", "note": ""},
        {"page": 127, "line": "свидбени судијама.", "find": "свидбени", "replace": "свидебени", "note": ""},
    ]


def test_collect_refuses_a_file_without_its_corrections_list(tmp_path):
    """A misspelt key would otherwise pass for „nothing to correct", and a reviewer's work
    would vanish without a word."""
    out = corrections_root(tmp_path)
    put_json(out / "p-110.json", {"page": 110, "corections": [{"line": "реч", "find": "а", "replace": "б"}]})

    result = review.collect(tmp_path, out)

    assert result["valid"] == []
    assert [(entry["file"], entry["reason"]) for entry in result["invalid"]] == [
        ("p-110.json", "no 'corrections' list in the file")
    ]


def test_collect_reports_files_it_cannot_use(tmp_path):
    out = corrections_root(tmp_path)
    (out / "p-110.json").write_text("{not json", encoding="utf-8")
    put_json(out / "p-009.json", {"page": 9, "corrections": []})
    put_json(out / "notes.json", {"corrections": []})

    result = review.collect(tmp_path, out)

    assert [(entry["file"], entry["index"]) for entry in result["invalid"]] == [
        ("notes.json", None),
        ("p-009.json", None),
        ("p-110.json", None),
    ]
    reasons = [entry["reason"] for entry in result["invalid"]]
    assert reasons[0] == "no page number in the file or its name"
    assert reasons[1] == "no OCR page 9 under build/ocr"
    assert reasons[2].startswith("cannot read the file")


def test_a_change_is_small_when_it_touches_one_or_two_words_or_a_third_of_the_text():
    assert review.edit_distance("крв", "крв") == 0
    assert review.edit_distance("четрдесетнице", "четрдесетније") == 1
    assert review.edit_distance("бо", "жи") == 2

    assert review.small_change("реч", "друга реч"), "one word becomes two"
    assert review.small_change("две речи", "реч"), "two words become one"
    assert review.small_change("четрдесетнице", "четрдесетније"), "one letter in twelve"
    assert not review.small_change("вечери тајној", "твојој светињи")
    # letter case does not count: the same words in another case are a small change
    assert review.small_change("ГосПОДе ПОМИЛУЈ!", "Господе помилуј!")
    assert not review.small_change("ГосПОДе ПОМИЛУЈ!", "Господе опрости!")


def test_a_correction_that_mostly_sets_the_letter_case_is_accepted(fixtures, tmp_path):
    # the book prints this response in small capitals; the OCR reads them with a mixed case,
    # and with a letter too many
    put_json(tmp_path / "build/ocr/p-127.json", load(fixtures / "ocr" / "p-127.json"))
    out = tmp_path / "corrections"
    put_json(
        out / "p-127.json",
        {
            "page": 127,
            "corrections": [
                {
                    "line": "Онда: ГосСПОДе ПОМИЛУЈ! 40 пута",
                    "find": "ГосСПОДе ПОМИЛУЈ!",
                    "replace": "Господе помилуј!",
                },
            ],
        },
    )

    result = review.collect(tmp_path, out)

    assert result["invalid"] == []
    assert [entry["replace"] for entry in result["valid"]] == ["Господе помилуј!"]


def test_collect_command_writes_the_valid_corrections_and_lists_the_invalid_ones(tmp_path, capsys):
    out = corrections_root(tmp_path)
    put_json(
        out / "p-110.json",
        {
            "page": 110,
            "corrections": [
                {"line": "Песма 5.", "find": "Песма", "replace": "Ирмос"},
                {"line": "Песма 6.", "find": "Песма", "replace": "Ирмос"},
            ],
        },
    )
    put_json(
        out / "p-127.json",
        {
            "page": 127,
            "corrections": [
                {"line": "свидбени судијама.", "find": "свидбени", "replace": "свидебени"},
            ],
        },
    )

    assert cli(tmp_path, "collect", "--corrections", str(out)) == 1

    assert load(tmp_path / "build/review/corrections.json") == [
        {"page": 110, "line": "Песма 5.", "find": "Песма", "replace": "Ирмос", "note": ""},
        {"page": 127, "line": "свидбени судијама.", "find": "свидбени", "replace": "свидебени", "note": ""},
    ]
    out = capsys.readouterr().out
    assert "valid corrections: 2  invalid: 1" in out
    assert "INVALID p-110.json#1 | Песма 6. | 'Песма' | line matched 0 times" in out


def test_collect_exits_well_when_every_correction_is_valid(tmp_path):
    out = corrections_root(tmp_path)
    put_json(out / "p-110.json", {"page": 110, "corrections": []})

    assert cli(tmp_path, "collect", "--corrections", str(out)) == 0
    assert load(tmp_path / "build/review/corrections.json") == []


# --------------------------------------------------------------------- CLI


def test_the_step_registers_its_sub_commands():
    assert parse(["hints"]).command == "hints"
    assert parse(["marked"]).command == "marked"
    assert parse(["strips", "--pages", "110,127"]).pages == "110,127"
    assert parse(["strips"]).pages is None
    assert parse(["diff", "--transcriptions", "out"]).transcriptions == Path("out")
    assert parse(["collect", "--corrections", "out"]).corrections == Path("out")
    assert parse(["hints", "--hunspell", "/dict/sr"]).hunspell == "/dict/sr"
    assert parse(["marked", "--hunspell", "/dict/sr"]).hunspell == "/dict/sr"
    with pytest.raises(SystemExit):
        parse([])


def test_a_page_list_that_is_not_a_list_of_numbers_is_refused(tmp_path, capsys):
    strip_root(tmp_path, {"110": [1]})

    assert cli(tmp_path, "strips", "--pages", "110-") == 2
    assert "--pages" in capsys.readouterr().err


def test_pages_are_cut_once_each_even_when_named_twice(tmp_path):
    strip_root(tmp_path, {"110": [1]})

    assert len(review.write_strips(tmp_path, [110, 110])) == 1
