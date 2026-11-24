"""The command line (contract C8)."""

import pathlib
import sys
import types

import pytest
from molitvenik_tools import cli
from molitvenik_tools.assemble import StructureError
from molitvenik_tools.overrides import OverrideError


class FakeStep(types.ModuleType):
    """A step module with one argument, as the contract describes one."""

    def __init__(self, result=0, raises=None):
        super().__init__("fake_step")
        self.result, self.raises, self.calls = result, raises, []

    def add_parser(self, subparsers):
        parser = subparsers.add_parser("fake", help="do nothing useful")
        parser.add_argument("--times", type=int, default=1)
        return parser

    def run(self, args, root):
        self.calls.append((args.times, args.step, root))
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def fake(monkeypatch):
    step = FakeStep()
    monkeypatch.setattr(cli, "STEP_NAMES", ["fake"])
    monkeypatch.setattr(cli, "HELP", {"fake": "do nothing useful"})
    monkeypatch.setattr(cli, "MODULES", {"fake": ("fake_step", "run")})
    monkeypatch.setitem(sys.modules, "molitvenik_tools.fake_step", step)
    return step


# ---- help ---------------------------------------------------------------------------------------------


def test_help_lists_every_step_of_the_pipeline(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in ("fetch", "ocr", "ia-ocr", "clean", "assemble", "check", "review"):
        assert name in out
    assert cli.main([]) == 2  # no step: the help, and a usage error
    assert "steps:" in capsys.readouterr().err


def test_the_steps_are_in_the_order_of_the_pipeline():
    assert [name for name, _ in cli.STEPS] == [
        "fetch",
        "ocr",
        "ia-ocr",
        "clean",
        "assemble",
        "check",
        "review",
    ]


def test_check_is_the_second_entry_point_of_assemble():
    assert cli.MODULES["check"] == ("assemble", "run_check")
    assert cli.MODULES["ia-ocr"] == ("iaocr", "run")


def test_the_help_of_a_step_shows_its_own_arguments_and_the_root(fake, capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["fake", "--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert "--times" in out and "--root" in out and "do nothing useful" in out
    assert fake.calls == []


def test_the_help_of_a_real_step(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["clean", "--help"])
    assert stop.value.code == 0
    assert "--root" in capsys.readouterr().out


# ---- the root -----------------------------------------------------------------------------------------


def test_the_root_is_the_nearest_directory_with_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert cli.find_root(deep) == tmp_path.resolve()


def test_the_root_falls_back_to_the_start(tmp_path):
    assert cli.find_root(tmp_path / "nowhere") == (tmp_path / "nowhere").resolve()


def test_the_root_is_found_from_the_working_directory(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    work = tmp_path / "tools"
    work.mkdir()
    monkeypatch.chdir(work)
    assert cli.find_root() == tmp_path.resolve()


def test_a_step_receives_its_arguments_and_the_root(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["fake", "--times", "3"]) == 0
    assert fake.calls == [(3, "fake", tmp_path.resolve())]


def test_an_explicit_root_wins(fake, tmp_path):
    assert cli.main(["fake", "--root", str(tmp_path)]) == 0
    assert fake.calls == [(1, "fake", pathlib.Path(tmp_path))]


# ---- exit statuses ------------------------------------------------------------------------------------


def test_the_exit_status_is_the_step_s_return_value(fake, capsys):
    assert cli.main(["fake"]) == 0
    other = FakeStep(result=7)
    fake.run = other.run  # type: ignore[method-assign]
    assert cli.main(["fake"]) == 7


def test_a_missing_module_says_so_and_exits_with_three(monkeypatch, capsys):
    monkeypatch.setattr(cli, "STEP_NAMES", ["clean"])
    monkeypatch.setattr(cli, "MODULES", {"clean": ("no_such_module", "run")})
    assert cli.main(["clean"]) == 3
    assert capsys.readouterr().err == 'step "clean" is not available yet\n'


def test_an_unknown_step_is_a_usage_error(capsys):
    assert cli.main(["nema-me"]) == 2
    err = capsys.readouterr().err
    assert "unknown step 'nema-me'" in err and "steps:" in err


def test_a_usage_error_of_the_step_itself(fake, capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["fake", "--nema"])
    assert stop.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
    assert fake.calls == []


@pytest.mark.parametrize(
    "error", [OverrideError("page 110: 'x' occurs 0 times"), StructureError("anchor matched 0 blocks")]
)
def test_an_override_or_structure_error_is_printed_and_exits_with_two(fake, capsys, error):
    fake.raises = error
    assert cli.main(["fake"]) == 2
    assert capsys.readouterr().err == f"molitvenik fake: {error}\n"


def test_a_keyboard_interrupt_exits_with_130(fake, capsys):
    fake.raises = KeyboardInterrupt()
    assert cli.main(["fake"]) == 130
    assert capsys.readouterr().err == ""


def test_other_errors_are_not_swallowed(fake):
    fake.raises = RuntimeError("bug")
    with pytest.raises(RuntimeError, match="bug"):
        cli.main(["fake"])
