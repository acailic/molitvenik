"""fetch.py: addresses, skipping, retries, the PDF fallback and the step's wiring."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from molitvenik_tools import fetch
from molitvenik_tools.fetch import FetchError

ITEM = "https://archive.org/download/pravoslavni-molitvenik/page"


@pytest.fixture
def in_process_pool(monkeypatch):
    """The step's pool of processes, run in this process instead, so that the workers see a fake."""
    monkeypatch.setattr(fetch, "ProcessPoolExecutor", ThreadPoolExecutor)


def step_args(*argv):
    """Arguments as `molitvenik fetch …` hands them to the step (contract C8)."""
    parser = argparse.ArgumentParser()
    fetch.add_parser(parser.add_subparsers(dest="step", required=True))
    return parser.parse_args(["fetch", *argv])


def recording_download(monkeypatch, body=b"image"):
    """Make the downloader write `body`; returns the list of addresses it is asked for."""
    urls = []

    def fake(url, dest):
        urls.append(url)
        Path(dest).write_bytes(body)

    monkeypatch.setattr(fetch, "download", fake)
    return urls


def recording_pdftoppm(monkeypatch):
    """Make pdftoppm write a page file; returns the list of commands it was given."""
    calls = []

    def fake_run(cmd, **options):
        calls.append(cmd)
        Path(cmd[-1] + ".png").write_bytes(b"png")

    monkeypatch.setattr(fetch.subprocess, "run", fake_run)
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/pdftoppm")
    return calls


def test_archive_address_of_a_page_counts_leaves():
    # the Archive leaf is PDF page − 1
    assert fetch.page_url(9) == f"{ITEM}/n8_w2000.jpg"
    assert fetch.page_url(110) == f"{ITEM}/n109_w2000.jpg"
    assert fetch.page_file(9) == "n008_w2000.jpg"
    assert fetch.page_file(110) == "n109_w2000.jpg"
    assert fetch.pdf_page_file(9) == "p-009.png"


def test_step_defaults_to_the_text_pages():
    args = step_args()
    assert (args.first, args.last, args.jobs, args.pdf) == (8, 177, 4, None)


def test_fetched_page_is_not_downloaded_again(tmp_path, monkeypatch, in_process_pool):
    pages = tmp_path / "build" / "pages"
    pages.mkdir(parents=True)
    (pages / "n008_w2000.jpg").write_bytes(b"already here")

    def no_download(url, dest):
        raise AssertionError(f"downloaded {url}")

    monkeypatch.setattr(fetch, "download", no_download)
    assert fetch.run(step_args("--first", "9", "--last", "9"), tmp_path) == 0
    assert (pages / "n008_w2000.jpg").read_bytes() == b"already here"


def test_empty_page_file_is_downloaded_again(tmp_path, monkeypatch, in_process_pool):
    pages = tmp_path / "build" / "pages"
    pages.mkdir(parents=True)
    (pages / "n008_w2000.jpg").write_bytes(b"")
    urls = recording_download(monkeypatch)
    assert fetch.run(step_args("--first", "9", "--last", "9"), tmp_path) == 0
    assert urls == [f"{ITEM}/n8_w2000.jpg"]
    assert (pages / "n008_w2000.jpg").read_bytes() == b"image"


def test_run_downloads_every_page_and_records_the_source(tmp_path, monkeypatch, in_process_pool):
    urls = recording_download(monkeypatch)
    assert fetch.run(step_args("--first", "9", "--last", "10", "--jobs", "2"), tmp_path) == 0
    assert sorted(urls) == [f"{ITEM}/n8_w2000.jpg", f"{ITEM}/n9_w2000.jpg"]
    assert (tmp_path / "build" / "pages" / "n009_w2000.jpg").read_bytes() == b"image"
    source = tmp_path / "build" / "pages" / "SOURCE.txt"
    assert source.read_text(encoding="utf-8").strip() == "archive"


def test_run_twice_downloads_nothing_more(tmp_path, monkeypatch, in_process_pool):
    urls = recording_download(monkeypatch)
    args = step_args("--first", "9", "--last", "10")
    assert fetch.run(args, tmp_path) == 0
    assert fetch.run(args, tmp_path) == 0
    assert len(urls) == 2


def test_failed_pages_are_named_and_leave_no_source(tmp_path, monkeypatch, in_process_pool, capsys):
    def failing(url, dest):
        raise FetchError(f"could not download {url}")

    monkeypatch.setattr(fetch, "download", failing)
    assert fetch.run(step_args("--first", "9", "--last", "10"), tmp_path) == 1
    err = capsys.readouterr().err
    assert "page 9" in err
    assert "page 10" in err
    assert not (tmp_path / "build" / "pages" / "SOURCE.txt").exists()


def test_first_page_after_the_last_is_refused(tmp_path, capsys):
    assert fetch.run(step_args("--first", "10", "--last", "9"), tmp_path) == 1
    assert "--first" in capsys.readouterr().err


def test_failed_download_is_retried_three_times_and_then_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RETRY_DELAY", 0)
    attempts = []

    def failing(url):
        attempts.append(url)
        raise OSError("connection reset")

    monkeypatch.setattr(fetch, "http_get", failing)
    dest = tmp_path / "n008_w2000.jpg"
    with pytest.raises(FetchError, match="could not download"):
        fetch.download(f"{ITEM}/n8_w2000.jpg", dest)
    assert attempts == [f"{ITEM}/n8_w2000.jpg"] * 4  # the first try and three retries
    assert not dest.exists()
    assert not (tmp_path / "n008_w2000.jpg.part").exists()


def test_download_goes_on_after_a_failed_try(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RETRY_DELAY", 0)
    answers = iter([OSError("timed out"), b"image"])

    def flaky(url):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fetch, "http_get", flaky)
    dest = tmp_path / "build" / "pages" / "n008_w2000.jpg"
    fetch.download(f"{ITEM}/n8_w2000.jpg", dest)
    assert dest.read_bytes() == b"image"
    assert not dest.with_name(dest.name + ".part").exists()


def test_empty_response_is_a_failed_try(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RETRY_DELAY", 0)
    monkeypatch.setattr(fetch, "http_get", lambda url: b"")
    dest = tmp_path / "n008_w2000.jpg"
    with pytest.raises(FetchError):
        fetch.download(f"{ITEM}/n8_w2000.jpg", dest)
    assert not dest.exists()


def test_pdf_page_is_rendered_by_pdftoppm_at_150_dpi(tmp_path, monkeypatch):
    calls = recording_pdftoppm(monkeypatch)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "pages").mkdir()
    assert fetch.render_page(9, tmp_path / "pages", pdf) == "fetched"
    (cmd,) = calls
    assert cmd[0] == "pdftoppm"
    assert cmd[cmd.index("-r") + 1] == "150"
    assert "-png" in cmd
    assert "-singlefile" in cmd
    assert cmd[cmd.index("-f") + 1] == cmd[cmd.index("-l") + 1] == "9"
    assert cmd[-2:] == [str(pdf), str(tmp_path / "pages" / "p-009")]
    assert (tmp_path / "pages" / "p-009.png").read_bytes() == b"png"


def test_rendered_page_is_not_rendered_again(tmp_path, monkeypatch):
    def no_run(cmd, **options):
        raise AssertionError(f"ran {cmd}")

    monkeypatch.setattr(fetch.subprocess, "run", no_run)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "p-009.png").write_bytes(b"already here")
    assert fetch.render_page(9, pages, tmp_path / "book.pdf") == "skipped"
    assert (pages / "p-009.png").read_bytes() == b"already here"


def test_run_with_a_pdf_renders_the_pages_and_records_the_pdf(tmp_path, monkeypatch, in_process_pool):
    calls = recording_pdftoppm(monkeypatch)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF")
    args = step_args("--first", "9", "--last", "10", "--pdf", str(pdf))
    assert fetch.run(args, tmp_path) == 0
    assert sorted(cmd[-1] for cmd in calls) == [
        str(tmp_path / "build" / "pages" / "p-009"),
        str(tmp_path / "build" / "pages" / "p-010"),
    ]
    source = tmp_path / "build" / "pages" / "SOURCE.txt"
    assert source.read_text(encoding="utf-8").strip() == str(pdf.resolve())


def test_run_with_a_pdf_names_pdftoppm_when_it_is_not_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch.shutil, "which", lambda name: None)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF")
    assert fetch.run(step_args("--pdf", str(pdf)), tmp_path) == 1
    assert "pdftoppm" in capsys.readouterr().err


def test_run_with_a_pdf_that_is_not_there_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "/usr/bin/pdftoppm")
    pdf = tmp_path / "book.pdf"
    assert fetch.run(step_args("--pdf", str(pdf)), tmp_path) == 1
    assert "book.pdf" in capsys.readouterr().err


def test_step_runs_on_its_own(tmp_path, monkeypatch, in_process_pool):
    # `uv run python -m molitvenik_tools.fetch …` finds the root from the current directory
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    urls = recording_download(monkeypatch)
    assert fetch.main(["--first", "9", "--last", "9"]) == 0
    assert urls == [f"{ITEM}/n8_w2000.jpg"]
    assert (tmp_path / "build" / "pages" / "SOURCE.txt").exists()


def test_step_runs_on_its_own_from_elsewhere_with_a_root(tmp_path, monkeypatch, in_process_pool):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    urls = recording_download(monkeypatch)
    # --root goes anywhere among the options of the step
    assert fetch.main(["--first", "9", "--root", str(tmp_path), "--last", "9"]) == 0
    assert urls == [f"{ITEM}/n8_w2000.jpg"]
    assert (tmp_path / "build" / "pages" / "n008_w2000.jpg").read_bytes() == b"image"
    assert not (elsewhere / "build").exists()
