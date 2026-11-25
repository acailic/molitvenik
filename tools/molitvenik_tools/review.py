"""Reviewer material for checking the transcription (design, section 6).

`hints` writes a text bundle per page with the words that look wrong. `marked` picks the
content lines a reviewer has to look at: a suspected word, or a second reading of the page
that disagrees with ours. `strips` cuts those lines out of the full-resolution scan.
`diff` compares the OCR lines with a transcription made from the image alone. `collect`
checks the corrections the reviewers write and merges the valid ones into one file.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont

CYR = re.compile(r"[А-Яа-яЀ-ӿ]")
LETTER = re.compile(r"[^\W\d_]")
DIGIT = re.compile(r"\d")
# Cut from both ends of a token before it is looked at. The hyphen stays: it marks a word
# that continues on the next line.
PUNCT = "„“”‘’«»…([{<.,:;!?)]}>|/=·~+*\"'—–"
# Latin letters that the OCR writes in place of Cyrillic ones of the same shape.
LOOKALIKE = str.maketrans(
    {
        "a": "а",
        "c": "с",
        "e": "е",
        "h": "н",
        "i": "и",
        "j": "ј",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
    }
)
SENTENCE_END = ".!?:…”«»"
INDENT = 45  # page pixels right of the page's first word where a paragraph starts
RARE_CAPITAL = 2  # … how often at most a word may be capitalised in mid-sentence to be worth a hint
MAX_HINTS = 45  # listed per page
MAX_NOTE = 200
ZOOM = 0.72  # strips are cut from the full-resolution scan and shown at this zoom
MAX_SHEET_HEIGHT = 1800  # taller images are shrunk by the reviewers' viewer until they blur
OTHER = " ‖ "  # between the lines of the other reading that are named at one line of ours
PAD_X = 20  # page pixels of margin on each side of the text column
LABEL_W, LABEL_SIZE, GAP = 64, 40, 14
TINT = (255, 222, 90, 70)  # yellow, a quarter opaque
LABEL_COLOR = (170, 20, 20)

# Why a word is suspected, the most suspicious first.
LATIN, TWO_READINGS, UNKNOWN, DIGIT_IN_WORD, INNER_CAPS, ONE_READING, MID_CAPITAL = range(1, 8)
REASONS = {
    LATIN: "Latin letters",
    TWO_READINGS: "two readings disagree",
    UNKNOWN: "not in dictionary",
    DIGIT_IN_WORD: "digit inside the word",
    INNER_CAPS: "capital letter inside the word",
    ONE_READING: "one reading differs",
    MID_CAPITAL: "capital in mid-sentence, rare",
}


class ReviewError(ValueError):
    """A step cannot do its work: an input is missing or does not fit. The message says what."""


class Hint(NamedTuple):
    """A suspected word: the page it is on, the line (its index among the page's lines), the
    word as read, and why it is suspected (smaller is more suspicious)."""

    page: int
    line: int
    word: str
    priority: int

    @property
    def reason(self) -> str:
        return REASONS[self.priority]


class Token(NamedTuple):
    """A content word with what the heuristics need to know about its surroundings."""

    page: int
    line: int
    text: str
    flags: tuple[str, ...]
    prev: str  # the word before it on the page, "" at the start of the page
    follows: str  # the word after it on the page, "" at the end of the page
    indented: bool  # its line starts a paragraph


class Word(NamedTuple):
    """A token of one reading and the index of the line it belongs to."""

    line: int
    text: str


class _Rejected(Exception):
    """A correction file or entry that cannot be used. The message says why."""


# ------------------------------------------------------------------ helpers


def content_lines(page: dict) -> list[tuple[int, dict]]:
    """The content lines of a page, each with its index among all the lines of the page."""
    return [(index, line) for index, line in enumerate(page["lines"]) if line["kind"] == "content"]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_pages(root: Path) -> list[dict]:
    """Every OCR page under build/ocr, in page order."""
    paths = sorted((root / "build" / "ocr").glob("p-*.json"))
    if not paths:
        raise ReviewError(f"no OCR pages under {root / 'build' / 'ocr'}: run `molitvenik ocr` first")
    return [load_json(path) for path in paths]


def read_page(root: Path, number: int) -> dict:
    path = root / "build" / "ocr" / f"p-{number:03d}.json"
    if not path.exists():
        raise ReviewError(f"no OCR page {number} under build/ocr")
    return load_json(path)


def second_reading(root: Path, number: int) -> list[str] | None:
    """The Archive's OCR lines of a page (contract C3); None when there is none."""
    path = root / "build" / "ia-ocr" / f"p-{number:03d}.json"
    return load_json(path)["lines"] if path.exists() else None


def page_number(data: dict, path: Path) -> int | None:
    """The page a JSON file is about: its "page", else the number at the end of its name."""
    number = data.get("page") if isinstance(data, dict) else None
    if number is None and path.stem.rpartition("-")[2].isdigit():
        number = int(path.stem.rpartition("-")[2])
    return number if type(number) is int else None


def load_allowlist(root: Path) -> set[str]:
    """The words accepted although the dictionary does not know them."""
    path = Path(root) / "data" / "lexicon-allowlist.txt"
    if not path.exists():
        raise ReviewError(f"{path} is missing: the words that the dictionary does not know")
    return set(path.read_text(encoding="utf-8").lower().split())


# -------------------------------------------------------------------- hints


def page_tokens(page: dict) -> list[Token]:
    """The content words of a page in reading order."""
    words = [(index, line, word) for index, line in content_lines(page) for word in line["words"]]
    if not words:
        return []
    left_min = min(word["left"] for _, _, word in words)
    tokens = []
    for number, (index, line, word) in enumerate(words):
        before = words[number - 1][2]["text"] if number else ""
        after = words[number + 1][2]["text"] if number + 1 < len(words) else ""
        tokens.append(
            Token(
                page["page"],
                index,
                word["text"],
                tuple(word["flags"]),
                before,
                after,
                line["words"][0]["left"] - left_min >= INDENT,
            )
        )
    return tokens


def dictionary_forms(token: Token) -> list[str]:
    """The forms of a word that may stand in the dictionary. None for the continuation of a word
    broken at the end of a line (it is not a word of its own) nor for tokens too short to be
    worth a hint; for a word broken at its end, the joined word and the stem."""
    bare = token.text.strip(PUNCT)
    if token.prev.endswith("-") or len(LETTER.findall(bare)) < 2 or not CYR.search(bare):
        return []
    word = bare.lower()
    if word.endswith("-") and token.follows:
        stem = word[:-1]
        return [stem + token.follows.strip(PUNCT).lower(), stem]
    return [word]


def mid_sentence_capital(token: Token) -> bool:
    """A capital letter where no sentence or paragraph starts: the usual sign of small capitals
    in the print, or of a word that is not what it should be."""
    text, before = token.text, token.prev
    return (
        bool(before)
        and not token.indented
        and not before.endswith("-")
        and not text.endswith("-")
        and len(text) > 1
        and text[0].isupper()
        and before[-1] not in SENTENCE_END
    )


def word_hint(token: Token, unknown: set[str], allowlist: set[str], capitals: Counter) -> Hint | None:
    """Why a word is suspected (its strongest reason), or None when it is not."""
    bare = token.text.strip(PUNCT)
    if len(LETTER.findall(bare)) < 2:
        # A single letter or a symbol is not worth a hint, with two exceptions: a digit next
        # to a letter is a misread however short the word is (the print's „ч0-" and „утробе7"),
        # and a number on which another reading differs may be a wrong digit in a heading
        # („Кондак !" for „Кондак 1").
        if LETTER.search(bare) and DIGIT.search(bare):
            return Hint(token.page, token.line, token.text, DIGIT_IN_WORD)
        if DIGIT.search(bare) and any(flag.startswith("differs:") for flag in token.flags):
            return Hint(token.page, token.line, token.text, ONE_READING)
        return None
    word = bare.lower()
    forms = dictionary_forms(token)
    differing = sum(flag.startswith("differs:") for flag in token.flags)
    reasons = (
        ("latin-letters" in token.flags, LATIN),
        (differing == 2, TWO_READINGS),
        (bool(forms) and word not in allowlist and all(form in unknown for form in forms), UNKNOWN),
        (bool(DIGIT.search(bare)), DIGIT_IN_WORD),
        ("has-inner-caps" in token.flags, INNER_CAPS),
        (differing == 1, ONE_READING),
        (
            mid_sentence_capital(token) and word not in allowlist and capitals[word] <= RARE_CAPITAL,
            MID_CAPITAL,
        ),
    )
    return next((Hint(token.page, token.line, token.text, why) for holds, why in reasons if holds), None)


def suspected_words(pages: list[dict], unknown: set[str], allowlist: set[str]) -> list[Hint]:
    """The suspected words of `pages`, the most suspicious first: by reason, then page and line."""
    tokens = [token for page in pages for token in page_tokens(page)]
    capitals = Counter(token.text.strip(PUNCT).lower() for token in tokens if mid_sentence_capital(token))
    hints = [hint for token in tokens if (hint := word_hint(token, unknown, allowlist, capitals))]
    hints.sort(key=lambda hint: (hint.priority, hint.page, hint.line))
    return hints


def hints_text(page: dict, hints: list[Hint]) -> str:
    """The text bundle of one page: its content lines, numbered, then the suspected words."""
    content = content_lines(page)
    number_of = {index: number for number, (index, _) in enumerate(content, 1)}
    book_page = page.get("book_page", page["page"] + 3)
    lines = [f"PDF page {page['page']} (book page {book_page}). {len(content)} content lines."]
    lines += [f"{number_of[index]:02d}| {line['text']}" for index, line in content]
    if hints:
        lines.append("Suspected words:")
        lines += [f'{number_of[hint.line]:02d} "{hint.word}" ({hint.reason})' for hint in hints]
    return "\n".join(lines) + "\n"


def unknown_words(forms: set[str], base: str, binary: str = "hunspell") -> set[str] | None:
    """The forms that the dictionary rejects. Hunspell is run once, with `-d <base> -l -i
    UTF-8` and the forms on stdin. None when hunspell cannot be run."""
    if not forms:
        return set()
    try:
        run = subprocess.run(
            [binary, "-d", base, "-l", "-i", "UTF-8"],
            input="\n".join(sorted(forms)) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if run.returncode != 0:
        raise ReviewError(f"hunspell failed on the dictionary {base}: {run.stderr.strip()}")
    return {line.strip() for line in run.stdout.splitlines() if line.strip()}


def dictionary_unknown(pages: list[dict], hunspell: str | None, unknown: set[str] | None = None) -> set[str]:
    """The word forms of `pages` that the dictionary rejects.

    `unknown` is the set itself (tests inject it, so that they never run hunspell); when it
    is None the forms are asked from hunspell at the base path `hunspell`. Without a dictionary
    the "not in dictionary" reason is left out, and that is printed.
    """
    if unknown is not None:
        return set(unknown)
    if hunspell is None:
        print("no --hunspell: words are not checked against the dictionary")
        return set()
    forms = {form for page in pages for token in page_tokens(page) for form in dictionary_forms(token)}
    rejected = unknown_words(forms, hunspell)
    if rejected is None:
        print("hunspell not found: words are not checked against the dictionary")
        return set()
    return rejected


def write_hints(
    root, allowlist: set[str], hunspell: str | None = None, *, unknown: set[str] | None = None
) -> list[Path]:
    """Write build/review/hints/p-NNN.txt for every OCR page and return the files written."""
    root = Path(root)
    pages = load_pages(root)
    by_page: dict[int, list[Hint]] = defaultdict(list)
    for hint in suspected_words(pages, dictionary_unknown(pages, hunspell, unknown), allowlist):
        by_page[hint.page].append(hint)
    written = []
    listed = 0
    for page in pages:
        shown = by_page.get(page["page"], [])[:MAX_HINTS]
        listed += len(shown)
        path = root / "build" / "review" / "hints" / f"p-{page['page']:03d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(hints_text(page, shown), encoding="utf-8")
        written.append(path)
    words = sum(len(line["words"]) for page in pages for _, line in content_lines(page))
    print(f"pages={len(pages)} words={words} hinted_words={listed}")
    return written


# ------------------------------------------------------- lines to adjudicate


def norm(text: str) -> str:
    """A token as two readings are compared: punctuation cut from both ends, Latin look-alikes
    read as Cyrillic, lower-case. "" for a token with neither a letter nor a digit (spacing
    artefacts). A number counts: „Кондак 1" and „Кондак 11" are not the same heading."""
    token = text.strip(PUNCT).translate(LOOKALIKE).lower()
    return token if LETTER.search(token) or DIGIT.search(token) else ""


def normalised(tokens: list[str]) -> list[str]:
    return [token for text in tokens if (token := norm(text))]


def kept(tokens: list[str]) -> list[str]:
    """The tokens that have a letter or a digit, as they were read."""
    return [text for text in tokens if norm(text)]


def book_vocabulary(pages: list[dict]) -> set[str]:
    """Every word of at least three letters that stands in the content lines of `pages`,
    normalised: it tells a word of the book from the marks another reading makes of a page
    number."""
    return {
        norm(token)
        for page in pages
        for _, line in content_lines(page)
        for token in line["text"].split()
        if len(LETTER.findall(norm(token))) >= 3
    }


def page_furniture(lines: list[str], page: dict, vocabulary: set[str] | None = None) -> set[int]:
    """The indexes of the lines of another reading that say nothing about our text: its running
    title (which the OCR sets apart as a header), with or without stray marks, and its page
    number, also when the number was read into a line of marks and stray letters (the Archive's
    „22 сы пп аат"). A line with a real word besides the number is not page furniture: it may
    be „Кондак 1".

    The last line of the other reading is judged by what it holds rather than by the number:
    when it carries a number and none of its words stands in our lines, nor in `vocabulary`
    (the words of the whole book, see `book_vocabulary`), it is the page number among marks,
    though the number was misread („мн 184" for 84) or glued to more than two words. A line
    of ours that was lost altogether and carries a number („Кондак 11") keeps its words, and
    so is not taken for the page number. Without a vocabulary only a line of digits and marks
    is taken for the page number."""
    titles = {line_shapes(line["text"])[1] for line in page["lines"] if line["kind"] == "header"}
    numbers = {
        norm(token) for line in page["lines"] if line["kind"] == "footer" for token in line["text"].split()
    }
    numbers.add(str(page.get("book_page", page["page"] + 3)))  # the number the page carries in print
    numbers.discard("")
    our_words = {norm(token) for _, line in content_lines(page) for token in line["text"].split()}
    furniture = set()
    for index, text in enumerate(lines):
        joined, letters = line_shapes(text)
        tokens = text.split()
        words = [token for token in tokens if len(LETTER.findall(norm(token))) >= 3]
        numbered = any(norm(token).isdigit() for token in tokens)
        if not joined or joined.isdigit() or letters in titles:
            furniture.add(index)
        elif numbered and len(words) < 2 and any(norm(token) in numbers for token in tokens):
            furniture.add(index)
        elif (
            index == len(lines) - 1
            and numbered
            and not any(norm(token) in our_words for token in words)
            and (
                not words  # digits and marks only
                or (vocabulary is not None and not any(norm(token) in vocabulary for token in words))
            )
        ):
            furniture.add(index)
    return furniture


def line_shapes(text: str) -> tuple[str, str]:
    """A line as two strings that survive small misreadings: its words normalised and joined,
    and its letters alone."""
    joined = "".join(norm(token) for token in text.split())
    return joined, "".join(char for char in joined if char.isalpha())


def disagreements(a: list[Word], b: list[Word]) -> list[tuple[int, int, int, int]]:
    """Where two sequences of tokens disagree: the start and end of each differing run on both
    sides. A run counts when it has at most two tokens on either side; longer ones are lines
    broken differently, not misread words. Tokens that are the same word but differ in letter
    case or punctuation count as a run of one."""
    runs = []
    opcodes = SequenceMatcher(
        None, [norm(w.text) for w in a], [norm(w.text) for w in b], autojunk=False
    ).get_opcodes()
    for tag, p1, p2, q1, q2 in opcodes:
        if tag == "equal":
            runs += [
                (p, p + 1, q, q + 1)
                for p, q in zip(range(p1, p2), range(q1, q2), strict=True)
                if a[p].text.translate(LOOKALIKE) != b[q].text.translate(LOOKALIKE)
            ]
        elif p2 - p1 <= 2 and q2 - q1 <= 2:
            runs.append((p1, p2, q1, q2))
    return runs


def beside(items: list[Word], start: int, end: int) -> list[Word]:
    """The tokens of a differing run, or the one just before the run when it has none."""
    return items[start:end] or items[max(start - 1, 0) : max(start - 1, 0) + 1]


PAIR_SHARE = 0.5  # how much of their tokens two lines must share to be the same printed line


def pair_lines(ours: list[str], theirs: list[str]) -> dict[int, int]:
    """Which line of `theirs` is which line of `ours` (offsets into both), inside a block that
    does not line up: the pair that shares most tokens is taken first, then the next, until no
    pair shares at least PAIR_SHARE of them. A line of `theirs` that is left stands in no line
    of ours."""
    shares = sorted(
        (
            (SequenceMatcher(None, theirs[t].split(), ours[o].split(), autojunk=False).ratio(), t, o)
            for t in range(len(theirs))
            for o in range(len(ours))
        ),
        reverse=True,
    )
    pairs: dict[int, int] = {}
    for share, t, o in shares:
        if share < PAIR_SHARE:
            break
        if t not in pairs and o not in pairs.values():
            pairs[t] = o
    return pairs


def diff_against(page: dict, lines: list[str], vocabulary: set[str] | None = None) -> list[dict]:
    """The OCR lines of `page` on which another reading of the page (`lines`) disagrees with
    ours, in line order. An entry names the line (`line_index` is its index among the lines of
    the page, `line` its text), gives the other reading of it (`other`) and the tokens that
    differ (`diffs`: pairs of [ours, theirs]).

    A line that only the other reading has is reported against our line before it (or our
    first line) with nothing on our side and named under `extra`: a printed line that our OCR
    does not have at all. With `only_other` true that is all the other reading says at our
    line. That holds inside a block of lines that does not line up as well: the lines are
    paired first, and a line of the other reading that pairs with none of ours is such a line.
    The running title and the page number of the other reading do not count."""
    content = content_lines(page)
    ours = [[word["text"] for word in line["words"]] for _, line in content]
    furniture = page_furniture(lines, page, vocabulary)
    their_lines = [line for index, line in enumerate(lines) if index not in furniture]
    theirs = [line.split() for line in their_lines]
    our_text = [" ".join(normalised(tokens)) for tokens in ours]
    their_text = [" ".join(normalised(tokens)) for tokens in theirs]
    found: dict[int, dict] = {}

    def note(index: int, shown: list[tuple[int, str]], diff: dict, *, alone: bool = False) -> None:
        """What the other reading says at one of our lines: its lines, each with its number
        among its lines so that several are shown in reading order, and one disagreement;
        ``alone`` when that disagreement is a line of the other reading that stands in none of
        ours."""
        entry = found.setdefault(index, {"read": {}, "diffs": []})
        for number, line in shown:
            entry["read"][number] = line
        entry["diffs"].append((shown[0][0], diff))
        entry["alone"] = entry.get("alone", 0) + alone
        if alone:
            entry.setdefault("extra", []).append(shown[0][0])

    def unpaired(note_index: int, number: int) -> None:
        extra = [Word(number, text) for text in kept(theirs[number])]
        if extra:
            note(
                note_index,
                [(number, their_lines[number])],
                {"ours": [], "theirs": [w.text for w in extra]},
                alone=True,
            )

    # The lines are put side by side first. The lines of a block that does not line up are
    # then compared word by word, so that different line breaks do not count.
    blocks = SequenceMatcher(None, our_text, their_text, autojunk=False).get_opcodes()
    for _, i1, i2, j1, j2 in blocks:
        if i1 == i2:
            for number in range(j1, j2):
                unpaired(max(0, i1 - 1), number)
            continue
        # Where the other reading has more lines than ours in the block, a line of it that
        # pairs with none of ours is a line our OCR does not have: it stands between two of our
        # lines and is named with the first of them. Without a surplus the lines are the same
        # lines read another way, and only runs of one or two tokens count, as before.
        if j2 - j1 > i2 - i1:
            pairs = pair_lines(our_text[i1:i2], their_text[j1:j2])
            # A line of theirs whose every word is a word of ours in this block is one of our
            # lines broken another way, not a line we lack.
            ours_here = Counter(token for k in range(i1, i2) for token in kept(ours[k]))
            lost = [t for t in range(j2 - j1) if t not in pairs and Counter(kept(theirs[j1 + t])) - ours_here]
            for t in lost:
                after = [o for later, o in pairs.items() if later > t]
                before = [o for later, o in pairs.items() if later < t]
                if after:
                    unpaired(max(0, i1 + min(after) - 1), j1 + t)
                else:
                    unpaired(i1 + max(before) if before else max(0, i1 - 1), j1 + t)
            paired = [j for j in range(j1, j2) if j - j1 not in lost]
        else:
            paired = list(range(j1, j2))
        a = [Word(k, text) for k in range(i1, i2) for text in kept(ours[k])]
        b = [Word(j, text) for j in paired for text in kept(theirs[j])]
        for p1, p2, q1, q2 in disagreements(a, b):
            ours_here, theirs_here = beside(a, p1, p2), beside(b, q1, q2)
            if not theirs_here:
                continue
            diff = {"ours": [w.text for w in a[p1:p2]], "theirs": [w.text for w in b[q1:q2]]}
            numbers = list(dict.fromkeys(w.line for w in theirs_here))
            for index in dict.fromkeys(w.line for w in ours_here):
                note(index, [(numbers[0], " ".join(their_lines[j] for j in numbers))], diff)
    entries = []
    for k in sorted(found):
        diffs = [diff for _, diff in sorted(found[k]["diffs"], key=lambda pair: pair[0])]
        entry = {
            "page": page["page"],
            "line_index": content[k][0],
            "line": content[k][1]["text"],
            "other": OTHER.join(text for _, text in sorted(found[k]["read"].items())),
            "diffs": diffs,
        }
        # The lines of the other reading that stand in none of ours are named under `extra`;
        # when they are all it says at our line, it has that line alone.
        if found[k].get("extra"):
            entry["extra"] = [their_lines[number] for number in sorted(set(found[k]["extra"]))]
            if found[k]["alone"] == len(diffs):
                entry["only_other"] = True
        entries.append(entry)
    return entries


def marked_lines(
    page: dict, second: list[str], hints: set[int], vocabulary: set[str] | None = None
) -> list[int]:
    """The content lines of `page` that a reviewer has to look at, as indexes into the page's
    lines: those in `hints` (a line carries a hint when one of its words is suspected) and
    those on which `second`, the other reading of the page, disagrees."""
    differing = {entry["line_index"] for entry in diff_against(page, second, vocabulary)}
    return sorted(set(hints) | differing)


def write_marked(
    root, allowlist: set[str], hunspell: str | None = None, *, unknown: set[str] | None = None
) -> dict:
    """Write build/review/marked.json, { "NNN": [line indexes] } for every OCR page (contract:
    the indexes are into the page's lines), and return it."""
    root = Path(root)
    pages = load_pages(root)
    hinted: dict[int, set[int]] = defaultdict(set)
    suspects = suspected_words(pages, dictionary_unknown(pages, hunspell, unknown), allowlist)
    for hint in suspects:
        hinted[hint.page].add(hint.line)
    vocabulary = book_vocabulary(pages)
    marked, no_second = {}, []
    for page in pages:
        second = second_reading(root, page["page"])
        if second is None:
            no_second.append(page["page"])
            second = []
        marked[f"{page['page']:03d}"] = marked_lines(
            page, second, hinted.get(page["page"], set()), vocabulary
        )
    write_json(root / "build" / "review" / "marked.json", marked)
    lines = sum(len(content_lines(page)) for page in pages)
    print(f"pages={len(pages)} content_lines={lines} marked={sum(len(v) for v in marked.values())}")
    if no_second:
        print("no second reading for pages: " + ", ".join(str(number) for number in no_second))
    return marked


# -------------------------------------------------------------------- strips


def page_image_path(root: Path, number: int) -> Path:
    """The full-resolution scan of a PDF page: the Archive's image (its leaf is the page
    number minus one) or, for the fallback source, a page rendered from the PDF."""
    pages = root / "build" / "pages"
    for name in (f"n{number - 1:03d}_w2000.jpg", f"p-{number:03d}.png"):
        if (pages / name).exists():
            return pages / name
    raise ReviewError(f"no page image for PDF page {number} under build/pages: run `molitvenik fetch` first")


def open_scan(root: Path, number: int, page: dict) -> Image.Image:
    """The scan of a page as an RGB image. It must have the size the OCR read, or the strips
    would not sit on the lines."""
    path = page_image_path(root, number)
    with Image.open(path) as scan:
        image = scan.convert("RGB")
    if "source_width" in page and (
        abs(image.width - page["source_width"]) > 2 or abs(image.height - page["source_height"]) > 2
    ):
        raise ReviewError(
            f"the scan {path.relative_to(root)} is {image.width}x{image.height}, "
            f"but the OCR of page {number} read a {page['source_width']}x"
            f"{page['source_height']} image: fetch the pages or run the OCR again"
        )
    return image


def image_scale(page: dict, image: Image.Image) -> float:
    """Scan pixels per page pixel: the OCR coordinates are half the size of the full scan."""
    if "source_width" in page:
        return page["source_width"] / page["width"]
    return image.width / page["width"]


def cut_strip(
    image: Image.Image,
    scale: float,
    column: tuple[int, int],
    centres: list[float],
    heights: list[float],
    k: int,
) -> Image.Image:
    """Line `k` tinted yellow, with the lines above and below it whole, cut from the scan and
    enlarged. The leading is tight, so the neighbours always show; the tint says which line
    is meant."""
    centre, height = centres[k], heights[k]
    above = centres[k - 1] if k > 0 else centre - 2 * height
    below = centres[k + 1] if k + 1 < len(centres) else centre + 2 * height
    left, top = int(column[0] * scale), max(0, int((above - 0.8 * height) * scale))
    right = min(image.width, int(column[1] * scale))
    bottom = min(image.height, int((below + 0.8 * height) * scale))
    strip = image.crop((left, top, right, bottom)).convert("RGBA")
    veil = Image.new("RGBA", strip.size, (0, 0, 0, 0))
    band = (int((centre - 0.6 * height) * scale) - top, int((centre + 0.6 * height) * scale) - top)
    ImageDraw.Draw(veil).rectangle((0, band[0], strip.width, band[1]), fill=TINT)
    strip = Image.alpha_composite(strip, veil).convert("RGB")
    return strip.resize((round(strip.width * ZOOM), round(strip.height * ZOOM)), Image.Resampling.LANCZOS)


def label_font() -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=LABEL_SIZE)  # Pillow 10.1 and later
    except TypeError:
        return ImageFont.load_default()


def strip_note(number: int, image: str, text: str, entry: dict | None) -> str:
    """The lines of the strips text file that describe one strip."""
    note = f"{number:02d}| [{image}] A: {text}"
    if entry:
        if entry["other"]:
            note += f"\n    B: {entry['other']}"
        note += "\n    differs: " + "; ".join(
            f"A [{' '.join(diff['ours']) or '—'}] / B [{' '.join(diff['theirs']) or '—'}]"
            for diff in entry["diffs"]
        )
    return note


def stack(strips: list[tuple[int, Image.Image]]) -> Image.Image:
    """Stack strips into one image, each with its number on the left."""
    sheet = Image.new(
        "RGB",
        (
            LABEL_W + max(strip.width for _, strip in strips),
            sum(strip.height for _, strip in strips) + GAP * (len(strips) - 1),
        ),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    y = 0
    for number, strip in strips:
        sheet.paste(strip, (LABEL_W, y))
        draw.text(
            (12, y + (strip.height - LABEL_SIZE) // 2), f"{number:02d}", fill=LABEL_COLOR, font=label_font()
        )
        y += strip.height + GAP
    return sheet


def pack(heights: list[int], limit: int = MAX_SHEET_HEIGHT) -> list[int]:
    """How many strips, in this order, go into each image so that no image is taller than
    `limit` pixels. A strip is never cut, so one taller than the limit stands alone in an image."""
    groups, height = [], 0
    for strip_height in heights:
        if not groups or height + GAP + strip_height > limit:
            groups.append(0)
            height = 0
        height += (GAP if groups[-1] else 0) + strip_height
        groups[-1] += 1
    return groups


def strips_sheets(
    page: dict, indexes: list[int], diffs: list[dict], image: Image.Image
) -> tuple[list[Image.Image], str]:
    """The images that show the marked lines of a page, each at most MAX_SHEET_HEIGHT pixels
    high, and the text of the file that describes them."""
    content = content_lines(page)
    position = {index: k for k, (index, _) in enumerate(content)}
    centres = [median(w["top"] + w["height"] / 2 for w in line["words"]) for _, line in content]
    heights = [median(w["height"] for w in line["words"]) for _, line in content]
    # the whole text column, with a margin on each side
    column = (
        max(0, min(line["left"] for _, line in content) - PAD_X),
        min(page["width"], max(line["right"] for _, line in content) + PAD_X),
    )
    scale = image_scale(page, image)
    by_line = {entry["line_index"]: entry for entry in diffs}
    strips = []  # number, line text, how the other reading differs, the strip itself
    for number, index in enumerate(sorted(indexes), 1):
        if index not in position:
            raise ReviewError(f"page {page['page']}: line {index} is marked but is not a content line")
        strip = cut_strip(image, scale, column, centres, heights, position[index])
        strips.append((number, page["lines"][index]["text"], by_line.get(index), strip))
    sheets, images, notes, start = [], [], [], 0
    for count, size in enumerate(pack([strip.height for *_, strip in strips]), 1):
        part = strips[start : start + size]
        start += size
        name = f"p-{page['page']:03d}-{count}.png"
        sheets.append(stack([(number, strip) for number, _, _, strip in part]))
        images.append(
            f"{name} (strips {part[0][0]}–{part[-1][0]})" if size > 1 else f"{name} (strip {part[0][0]})"
        )
        notes += [strip_note(number, name, line_text, entry) for number, line_text, entry, _ in part]
    book_page = page.get("book_page", page["page"] + 3)
    head = (
        f"PDF page {page['page']} (book page {book_page}). Each numbered strip of the images "
        "shows a line to check, tinted yellow, with the lines above and below it whole. "
        "A is the line as our OCR read it, B the Archive's OCR of the same line, and "
        "`differs` lists the tokens they disagree about (— stands for nothing).\n"
        "Images: " + ", ".join(images) + "."
    )
    return sheets, head + "\n" + "\n".join(notes) + "\n"


def write_strips(root, pages: list[int]) -> list[Path]:
    """Cut a strip for every marked line of `pages` (of every page that has marked lines when
    `pages` is empty) and stack the strips of a page into as many images as it takes for none
    to be taller than MAX_SHEET_HEIGHT: build/review/strips/p-NNN-1.png, p-NNN-2.png, …, next
    to one text file per page. What an earlier run left there for these pages is replaced.
    Returns every image."""
    root = Path(root)
    marked_path = root / "build" / "review" / "marked.json"
    if not marked_path.exists():
        raise ReviewError("build/review/marked.json is missing: run `molitvenik review marked` first")
    marked = load_json(marked_path)
    numbers = sorted(set(pages)) if pages else sorted(int(key) for key in marked)
    directory = root / "build" / "review" / "strips"
    written = []
    for number in numbers:
        indexes = marked.get(f"{number:03d}", [])
        if not indexes:
            print(f"p-{number:03d}: no marked lines")
            continue
        page = read_page(root, number)
        diffs = diff_against(page, second_reading(root, number) or [], book_vocabulary([page]))
        sheets, text = strips_sheets(page, indexes, diffs, open_scan(root, number, page))
        directory.mkdir(parents=True, exist_ok=True)
        for pattern in (f"p-{number:03d}.png", f"p-{number:03d}-*.png"):
            for stale in directory.glob(pattern):
                stale.unlink()
        for count, sheet in enumerate(sheets, 1):
            path = directory / f"p-{number:03d}-{count}.png"
            sheet.save(path)
            written.append(path)
        (directory / f"p-{number:03d}.txt").write_text(text, encoding="utf-8")
        print(
            f"p-{number:03d}: {len(indexes)} strips in {len(sheets)} image{'' if len(sheets) == 1 else 's'}"
        )
    return written


# --------------------------------------------------------------------- diff


def write_diff(root, transcriptions_dir: Path) -> list[dict]:
    """Compare the OCR lines with the transcriptions in `transcriptions_dir` (one file per
    page, { "page": N, "lines": [...] }) and write build/review/diff.json. Returns the entries.

    An entry is as `diff_against` gives it, with `marked_before`: whether `review marked` had
    picked the line. That is what tells the errors the flags miss from the ones they caught;
    it is None when there is no build/review/marked.json.
    """
    root, transcriptions_dir = Path(root), Path(transcriptions_dir)
    marked_path = root / "build" / "review" / "marked.json"
    marked = load_json(marked_path) if marked_path.exists() else None
    files = sorted(transcriptions_dir.glob("*.json"))
    has_pages = any((root / "build" / "ocr").glob("p-*.json"))
    vocabulary = book_vocabulary(load_pages(root)) if has_pages else set()
    entries = []
    lines = 0
    for path in files:
        data = load_json(path)
        number = page_number(data, path)
        if number is None:
            raise ReviewError(f"{path.name}: no page number in the file or its name")
        page = read_page(root, number)
        lines += len(content_lines(page))
        for entry in diff_against(page, data.get("lines", []), vocabulary):
            entry["marked_before"] = (
                entry["line_index"] in marked.get(f"{number:03d}", []) if marked is not None else None
            )
            entries.append(entry)
    entries.sort(key=lambda entry: (entry["page"], entry["line_index"]))
    write_json(root / "build" / "review" / "diff.json", entries)
    print(f"pages={len(files)} lines={lines} with_disagreement={len(entries)}")
    if marked is None:
        print("no build/review/marked.json: the lines are not classified by `review marked`")
    else:
        before = sum(entry["marked_before"] for entry in entries)
        print(f"marked before: {before}  not marked: {len(entries) - before}")
    return entries


# ----------------------------------------------------------------- collect


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance: the fewest insertions, deletions and substitutions that turn
    `a` into `b`."""
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def small_change(find: str, replace: str) -> bool:
    """Whether a correction is small enough to be a fix of the print rather than a new text:
    one word replaced by one or two (or the other way round), or at most a third of `find`
    edited. Letter case is not counted: the same words in another case are a small change
    (small capitals come out of the OCR with a mixed case)."""
    if " " not in find and replace.count(" ") <= 1:
        return True
    if " " not in replace and find.count(" ") <= 1:
        return True
    return edit_distance(find.casefold(), replace.casefold()) <= max(1, len(find) // 3)


def read_corrections(path: Path) -> tuple[list, int]:
    """The corrections of one reviewer file and the number of the page they belong to."""
    try:
        data = load_json(path)
    except (OSError, ValueError) as exc:
        raise _Rejected(f"cannot read the file: {exc}") from exc
    number = page_number(data, path)
    if number is None:
        raise _Rejected("no page number in the file or its name")
    # A file without the list is refused, not taken for „nothing to correct": a misspelt key
    # would otherwise make a reviewer's work vanish without a word.
    if not isinstance(data, dict) or "corrections" not in data:
        raise _Rejected("no 'corrections' list in the file")
    corrections = data["corrections"]
    if not isinstance(corrections, list):
        raise _Rejected("corrections is not a list")
    return corrections, number


def locate(
    correction: dict, texts: list[tuple[int, str]], spans: dict[int, list[tuple[int, int]]]
) -> tuple[int, int, int]:
    """Where a correction acts: the position of its line among `texts` and the span of `find`
    inside that line as it was read. Raises _Rejected when it cannot be applied (contract C4:
    the line exists once, `find` once inside it, the change is small)."""
    if not isinstance(correction, dict):
        raise _Rejected("correction is not an object")
    line_text, find, replace = (correction.get(key) for key in ("line", "find", "replace"))
    if not all(isinstance(value, str) for value in (line_text, find, replace)):
        raise _Rejected("missing or non-string field")
    matches = [position for position, (_, text) in enumerate(texts) if text == line_text]
    if len(matches) != 1:
        raise _Rejected(f"line matched {len(matches)} times")
    if not find or line_text.count(find) != 1:
        raise _Rejected(f"find occurs {line_text.count(find)} times in line")
    if find == replace:
        raise _Rejected("no change")
    if not small_change(find, replace):
        raise _Rejected("too large a change")
    # All corrections of a line are applied together on the line as read, so they may not overlap.
    position = matches[0]
    start = line_text.index(find)
    span = (start, start + len(find))
    if any(start < end and begin < span[1] for begin, end in spans.get(position, [])):
        raise _Rejected("overlaps another correction on the line")
    spans.setdefault(position, []).append(span)
    return position, *span


def refused(file: str, position: int | None, number: int | None, correction: object, reason: str) -> dict:
    """The record of an invalid correction: where it came from and why it was refused."""
    fields = correction if isinstance(correction, dict) else {}
    return {
        "file": file,
        "index": position,
        "page": number,
        "line": fields.get("line"),
        "find": fields.get("find"),
        "replace": fields.get("replace"),
        "reason": reason,
    }


def collect(root, corrections_dir: Path) -> dict:
    """Check the reviewers' correction files against the OCR pages and return
    {"valid": [...], "invalid": [...]}.

    A file holds { "page": N, "corrections": [{ "line", "find", "replace", "note" }] } (contract
    C4). A valid entry is {"page", "line", "find", "replace", "note"}, ready for
    data/ocr-overrides.json; the valid ones are sorted by page and line. An invalid entry names
    its file and position and says why it was refused.
    """
    root, corrections_dir = Path(root), Path(corrections_dir)
    valid, where, invalid = [], [], []
    for path in sorted(corrections_dir.glob("*.json")):
        try:
            corrections, number = read_corrections(path)
            page_path = root / "build" / "ocr" / f"p-{number:03d}.json"
            if not page_path.exists():
                raise _Rejected(f"no OCR page {number} under build/ocr")
            texts = [(index, line["text"]) for index, line in content_lines(load_json(page_path))]
        except _Rejected as exc:
            invalid.append(refused(path.name, None, None, {}, str(exc)))
            continue
        spans: dict[int, list[tuple[int, int]]] = {}  # the spans the accepted corrections take
        for position, correction in enumerate(corrections):
            try:
                line, _, _ = locate(correction, texts, spans)
            except _Rejected as exc:
                invalid.append(refused(path.name, position, number, correction, str(exc)))
                continue
            valid.append(
                {
                    "page": number,
                    "line": texts[line][1],
                    "find": correction["find"],
                    "replace": correction["replace"],
                    "note": str(correction.get("note", ""))[:MAX_NOTE],
                }
            )
            where.append((number, line))
    ordered = sorted(zip(where, valid, strict=True), key=lambda pair: pair[0])
    return {"valid": [entry for _, entry in ordered], "invalid": invalid}


# ---------------------------------------------------------------------- CLI


def parse_pages(text: str) -> list[int]:
    """PDF page numbers from a comma-separated list."""
    try:
        return sorted({int(part) for part in text.split(",") if part.strip()})
    except ValueError:
        raise ReviewError(f"--pages expects page numbers separated by commas, not {text!r}") from None


def run_hints(args, root: Path) -> int:
    write_hints(root, load_allowlist(root), args.hunspell)
    return 0


def run_marked(args, root: Path) -> int:
    write_marked(root, load_allowlist(root), args.hunspell)
    return 0


def run_strips(args, root: Path) -> int:
    write_strips(root, parse_pages(args.pages) if args.pages else [])
    return 0


def run_diff(args, root: Path) -> int:
    write_diff(root, args.transcriptions)
    return 0


def run_collect(args, root: Path) -> int:
    """Collect the corrections; the exit status is 1 when some were refused, because a refused
    correction leaves a known error unfixed."""
    result = collect(root, args.corrections)
    write_json(root / "build" / "review" / "corrections.json", result["valid"])
    print(f"valid corrections: {len(result['valid'])}  invalid: {len(result['invalid'])}")
    for entry in result["invalid"]:
        place = entry["file"] if entry["index"] is None else f"{entry['file']}#{entry['index']}"
        print(f"  INVALID {place} | {str(entry['line'] or '-')[:40]} | {entry['find']!r} | {entry['reason']}")
    return 1 if result["invalid"] else 0


def run(args, root: Path) -> int:
    """Run one sub-command of the review step (contract C8)."""
    steps = {
        "hints": run_hints,
        "marked": run_marked,
        "strips": run_strips,
        "diff": run_diff,
        "collect": run_collect,
    }
    try:
        return steps[args.command](args, Path(root))
    except ReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def add_parser(subparsers) -> argparse.ArgumentParser:
    """Add the `review` step with its sub-commands to the CLI of the pipeline (contract C8)."""
    return build_parser(
        subparsers.add_parser(
            "review",
            help="hints, strips and comparisons for checking the text",
            description="Material for the reviewers who check the transcription against the scan.",
        )
    )


def build_parser(parser: argparse.ArgumentParser) -> None:
    """Add the sub-commands of the review step to `parser`."""
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def with_dictionary(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--hunspell",
            metavar="BASE",
            default=None,
            help="dictionary base path, the name without .aff and .dic "
            "(without it, words are not checked against a dictionary)",
        )

    hints = commands.add_parser(
        "hints", help="a text bundle per page with the suspected words under build/review/hints"
    )
    with_dictionary(hints)
    marked = commands.add_parser("marked", help="the lines to adjudicate: build/review/marked.json")
    with_dictionary(marked)
    strips = commands.add_parser("strips", help="the marked lines cut out of the scans: build/review/strips")
    strips.add_argument(
        "--pages", metavar="N,N,…", default=None, help="PDF pages; default: every page that has marked lines"
    )
    diff = commands.add_parser(
        "diff", help="OCR lines against transcriptions made from the image alone: build/review/diff.json"
    )
    diff.add_argument(
        "--transcriptions",
        type=Path,
        required=True,
        metavar="DIR",
        help='a file per page, { "page": N, "lines": [...] }',
    )
    corrections = commands.add_parser(
        "collect",
        help="check the reviewers' corrections: build/review/corrections.json "
        "(exit status 1 when some are invalid)",
    )
    corrections.add_argument(
        "--corrections",
        type=Path,
        required=True,
        metavar="DIR",
        help='a file per page, { "page": N, "corrections": [...] }',
    )


def main(argv: list[str] | None = None) -> int:
    """Run the step on its own:
    uv run python -m molitvenik_tools.review --root PATH strips --pages 110,127"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: the one this file is in)",
    )
    build_parser(parser)
    args = parser.parse_args(argv)
    return run(args, args.root)


if __name__ == "__main__":
    sys.exit(main())
