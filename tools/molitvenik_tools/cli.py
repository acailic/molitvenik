"""The command line: ``uv run molitvenik <step>`` (contract C8).

Each step lives in its own module and is imported only when it is called, so
that ``--help`` and the other steps keep working while one module is still
missing. A step module exposes ``add_parser(subparsers)`` and
``run(args, root)``; ``check`` is the second entry point of the ``assemble``
module.
"""

from __future__ import annotations

import argparse
import importlib
import pathlib
import sys

from molitvenik_tools.assemble import StructureError
from molitvenik_tools.overrides import OverrideError

# The steps in the order of the pipeline, with the line ``--help`` shows for each.
STEPS = [
    ("fetch", "download the page images of the book into build/pages/"),
    ("ocr", "read every page with Tesseract into build/ocr/"),
    ("ia-ocr", "reduce the Internet Archive's own OCR to lines, build/ia-ocr/"),
    ("clean", "apply the corrections and join the OCR lines into build/clean/book.json"),
    ("assemble", "build data/prayers.json from the cleaned text and the structure"),
    ("check", "run the text checks on the assembled prayer book"),
    ("review", "material for the reviewers: hints, marked, strips, diff, collect"),
]
STEP_NAMES = [name for name, _ in STEPS]
HELP = dict(STEPS)

# step name -> (module inside molitvenik_tools, function to call)
MODULES: dict[str, tuple[str, str]] = {
    "fetch": ("fetch", "run"),
    "ocr": ("ocr", "run"),
    "ia-ocr": ("iaocr", "run"),
    "clean": ("clean", "run"),
    "assemble": ("assemble", "run"),
    "check": ("assemble", "run_check"),
    "review": ("review", "run"),
}

EXIT_USAGE = 2
EXIT_MISSING_STEP = 3
EXIT_INTERRUPTED = 130


def find_root(start: pathlib.Path | None = None) -> pathlib.Path:
    """The repository root: the nearest directory at or above ``start`` that has pyproject.toml."""
    here = (start or pathlib.Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here


def load_step(name: str):
    """The module of a step and the function to run; ``ImportError`` when the module is missing."""
    module_name, function = MODULES[name]
    module = importlib.import_module(f"molitvenik_tools.{module_name}")
    return module, getattr(module, function)


def top_help() -> str:
    lines = ["usage: molitvenik <step> [--root PATH] ...", "", "steps:", ""]
    lines += [f"  {name:<10} {HELP[name]}" for name in STEP_NAMES]
    lines += ["", "Run `molitvenik <step> --help` for the arguments of a step."]
    return "\n".join(lines)


class _SingleStep:
    """Stands in for a group of sub-parsers that holds this one step.

    Step modules are written against ``subparsers.add_parser(name, help=…)``;
    this gives them the parser of the step and ignores any other step they
    describe (``assemble`` also describes ``check``).
    """

    def __init__(self, parser: argparse.ArgumentParser, name: str) -> None:
        self._parser = parser
        self._name = name

    def add_parser(self, name: str, **kwargs) -> argparse.ArgumentParser:
        if name == self._name:
            if "help" in kwargs and not self._parser.description:
                self._parser.description = kwargs["help"]
            return self._parser
        return argparse.ArgumentParser(prog=f"molitvenik {name}")  # not asked for: thrown away


def build_parser(name: str) -> argparse.ArgumentParser:
    """The parser of one step: the module's arguments under a common ``--root``."""
    parser = argparse.ArgumentParser(prog=f"molitvenik {name}", description=HELP[name])
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=None,
        help="repository root (default: the nearest directory above with pyproject.toml)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one step; the return value is the exit status."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(top_help(), file=sys.stderr)
        return EXIT_USAGE
    if argv[0] in ("-h", "--help"):
        print(top_help())
        return 0
    name = argv[0]
    if name not in STEP_NAMES:
        print(f"molitvenik: unknown step {name!r}", file=sys.stderr)
        print(top_help(), file=sys.stderr)
        return EXIT_USAGE
    try:
        module, function = load_step(name)
    except ImportError:
        print(f'step "{name}" is not available yet', file=sys.stderr)
        return EXIT_MISSING_STEP

    parser = build_parser(name)
    module.add_parser(_SingleStep(parser, name))
    args = parser.parse_args(argv[1:])
    args.step = name
    root = args.root if args.root is not None else find_root()
    try:
        return function(args, root)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except (OverrideError, StructureError) as exc:
        print(f"molitvenik {name}: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
