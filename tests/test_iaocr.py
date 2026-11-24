"""iaocr.py: the Archive's own OCR of the book (DjVu XML) as per-page line files."""

import argparse
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from molitvenik_tools import iaocr
from molitvenik_tools.fetch import FetchError

DJVU_URL = "https://archive.org/download/pravoslavni-molitvenik/Pravoslavni%20molitvenik_djvu.xml"


@pytest.fixture
def in_process_pool(monkeypatch):
    """The step's pool of processes, run in this process instead, so that the step is quick to test."""
    monkeypatch.setattr(iaocr, "ProcessPoolExecutor", ThreadPoolExecutor)


def step_args(*argv):
    """Arguments as `molitvenik ia-ocr …` hands them to the step (contract C8)."""
    parser = argparse.ArgumentParser()
    iaocr.add_parser(parser.add_subparsers(dest="step", required=True))
    return parser.parse_args(["ia-ocr", *argv])


def line(*words):
    """A LINE of WORDs at descending heights, as the Archive's XML holds them."""
    return (
        "<LINE>"
        + "".join(
            f'<WORD coords="{400 + 90 * i},700,{480 + 90 * i},640" x-confidence="96">{w}</WORD>'
            for i, w in enumerate(words)
        )
        + "</LINE>"
    )


def line_of(text):
    return line(*text.split(" "))


def column(*paragraphs):
    """A PAGECOLUMN of the given paragraphs."""
    body = "".join(f"<PARAGRAPH>{p}</PARAGRAPH>" for p in paragraphs)
    return f"<PAGECOLUMN><REGION>{body}</REGION></PAGECOLUMN>"


def djvu(*objects):
    """DjVu XML text with the given bodies of HIDDENTEXT, one page object each."""
    pages = "".join(
        f'<OBJECT usemap="book_{n:04d}.djvu" width="2110" height="3277">'
        f'<PARAM name="PAGE" value="book_{n:04d}.djvu"/><PARAM name="DPI" value="600"/>'
        f"<HIDDENTEXT>{body}</HIDDENTEXT></OBJECT>"
        for n, body in enumerate(objects)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE DjVuXML>\n'
        f"<DjVuXML>\n<BODY>\n{pages}\n</BODY>\n</DjVuXML>\n"
    )


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_one_file_per_page_object(tmp_path):
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(column(line("У", "име", "Оца")), column(line("С", "благословом"))), encoding="utf-8")
    assert iaocr.write_pages(xml, tmp_path / "out", jobs=2) == 2
    assert read(tmp_path / "out" / "p-001.json") == {"page": 1, "lines": ["У име Оца"]}
    assert read(tmp_path / "out" / "p-002.json") == {"page": 2, "lines": ["С благословом"]}
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["p-001.json", "p-002.json"]


def test_lines_are_kept_in_order_and_those_without_a_cyrillic_letter_are_dropped(tmp_path, in_process_pool):
    # The running title has a column of its own; the page number, a Latin word and marks are dropped.
    body = column(
        line("Молитвено", "правило", "пред", "Свето", "причешће"),
        line("Исцели,", "Господе,", "ране", "ду-"),
        line("|", "113"),
        line("Prologue", "7"),
        line("•", ".", "•,"),
    )
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(body, column(line("Крв."), line("Амин."))), encoding="utf-8")
    assert iaocr.write_pages(xml, tmp_path / "out") == 2
    assert read(tmp_path / "out" / "p-001.json") == {
        "page": 1,
        "lines": ["Молитвено правило пред Свето причешће", "Исцели, Господе, ране ду-"],
    }
    assert read(tmp_path / "out" / "p-002.json") == {"page": 2, "lines": ["Крв.", "Амин."]}


def test_columns_are_read_one_after_the_other(tmp_path, in_process_pool):
    body = column(line("Песма", "5.")) + column(line("Ирмос:", "Даваоче", "светлости"))
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(body), encoding="utf-8")
    iaocr.write_pages(xml, tmp_path / "out")
    assert read(tmp_path / "out" / "p-001.json")["lines"] == ["Песма 5.", "Ирмос: Даваоче светлости"]


def test_the_nth_object_is_leaf_n_and_a_page_without_text_gets_no_line(tmp_path, in_process_pool):
    # leaf 0, leaf 1 and leaf 2 are PDF pages 1, 2 and 3
    objects = [column(line("1")), column(line("Molitvenik")), column(line("Амин."))]
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(*objects), encoding="utf-8")
    assert iaocr.write_pages(xml, tmp_path / "out") == 3
    assert read(tmp_path / "out" / "p-001.json") == {"page": 1, "lines": []}
    assert read(tmp_path / "out" / "p-002.json") == {"page": 2, "lines": []}
    assert read(tmp_path / "out" / "p-003.json") == {"page": 3, "lines": ["Амин."]}


def test_words_are_joined_with_one_space_and_empty_ones_are_left_out():
    words = "<WORD> У </WORD><WORD></WORD><WORD>име</WORD><WORD>  </WORD><WORD>Оца</WORD>"
    obj = ET.fromstring(f"<OBJECT><HIDDENTEXT>{column(f'<LINE>{words}</LINE>')}</HIDDENTEXT></OBJECT>")
    assert iaocr.page_lines(obj) == ["У име Оца"]


@pytest.mark.parametrize("name", ["p-110", "p-127", "p-137"])
def test_fixture_page_comes_out_of_a_djvu_page_shaped_like_it(tmp_path, load_fixture, in_process_pool, name):
    expected = load_fixture("ia-ocr", name)
    page = expected["page"]
    running_title, *text = expected["lines"]
    objects = [column(line("Pravoslavni", "molitvenik"))] * (page - 1)
    objects.append(
        column(line(*running_title.split(" ")))
        + column("".join(map(line_of, text)) + line("|", str(page + 3)))
    )
    objects.append(column(line("Pravoslavni", "molitvenik")))
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(*objects), encoding="utf-8")
    assert iaocr.write_pages(xml, tmp_path / "out") == page + 1
    assert read(tmp_path / "out" / f"{name}.json") == expected


def test_run_writes_into_build_the_same_files_every_time(tmp_path, in_process_pool):
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(column(line("Амин."))), encoding="utf-8")
    args = step_args("--xml", str(xml))
    assert iaocr.run(args, tmp_path) == 0
    first = (tmp_path / "build" / "ia-ocr" / "p-001.json").read_bytes()
    assert iaocr.run(args, tmp_path) == 0
    assert (tmp_path / "build" / "ia-ocr" / "p-001.json").read_bytes() == first
    assert json.loads(first) == {"page": 1, "lines": ["Амин."]}


def test_step_defaults():
    args = step_args()
    assert (args.xml, args.jobs) == (None, 8)


def test_run_downloads_the_xml_when_it_is_not_given(tmp_path, monkeypatch, in_process_pool):
    calls = []

    def fake_download(url, dest):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(djvu(column(line("Амин."))), encoding="utf-8")

    monkeypatch.setattr(iaocr, "download", fake_download)
    assert iaocr.run(step_args(), tmp_path) == 0
    assert calls == [DJVU_URL]
    assert read(tmp_path / "build" / "ia-ocr" / "p-001.json") == {"page": 1, "lines": ["Амин."]}


def test_downloaded_xml_is_used_again(tmp_path, monkeypatch, in_process_pool):
    cached = tmp_path / "build" / "ia" / "djvu.xml"
    cached.parent.mkdir(parents=True)
    cached.write_text(djvu(column(line("Крв."))), encoding="utf-8")

    def no_download(url, dest):
        raise AssertionError(f"downloaded {url}")

    monkeypatch.setattr(iaocr, "download", no_download)
    assert iaocr.run(step_args(), tmp_path) == 0
    assert read(tmp_path / "build" / "ia-ocr" / "p-001.json") == {"page": 1, "lines": ["Крв."]}


def test_run_names_an_xml_file_that_is_not_there(tmp_path, capsys):
    assert iaocr.run(step_args("--xml", str(tmp_path / "nope.xml")), tmp_path) == 1
    assert "nope.xml" in capsys.readouterr().err


def test_run_names_a_failed_download(tmp_path, monkeypatch, capsys):
    def failing(url, dest):
        raise FetchError("could not download")

    monkeypatch.setattr(iaocr, "download", failing)
    assert iaocr.run(step_args(), tmp_path) == 1
    assert "could not download" in capsys.readouterr().err


def test_step_runs_on_its_own(tmp_path, monkeypatch, in_process_pool):
    # `uv run python -m molitvenik_tools.ia-ocr …` finds the root from the current directory
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    xml = tmp_path / "djvu.xml"
    xml.write_text(djvu(column(line("Амин."))), encoding="utf-8")
    assert iaocr.main(["--xml", str(xml)]) == 0
    assert read(tmp_path / "build" / "ia-ocr" / "p-001.json") == {"page": 1, "lines": ["Амин."]}
