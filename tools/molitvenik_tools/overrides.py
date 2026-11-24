"""Apply the proofreading corrections to the words of an OCR page.

A correction names a page, the exact text of one of its content lines and a
substring of that line, and says what the print shows there instead. The
corrections live in ``data/ocr-overrides.json``, so every change to the text is
visible in git and the text can be regenerated at any time. A correction may
add ``rubric`` (print the replaced words red or black) and ``left`` (the x of
the replaced words in the half-resolution page, for a word lost at the start of
a line).
"""

from __future__ import annotations

import copy


class OverrideError(ValueError):
    """A correction cannot be applied: its line or its ``find`` is not there."""


def apply_spans(line: dict, spans: list[tuple[int, int, str, bool | None]]) -> None:
    """Replace character spans of a line's text, in place.

    ``spans`` are ``(start, end, replacement, rubric)`` in the line text as it
    is now; they must not overlap. ``rubric`` is ``True`` to turn the replaced
    words red, ``False`` to turn them black, ``None`` to keep their colour.
    The line is split into words again on spaces. A word keeps its box, colour
    and confidence when the number of words is unchanged; otherwise every new
    word inherits them from the first replaced word.
    """
    words = line["words"]
    texts = [w["text"] for w in words]
    text = " ".join(texts)
    spans = sorted(spans, key=lambda span: (span[0], span[1]))
    for (_, end_a, _, _), (start_b, _, _, _) in zip(spans, spans[1:], strict=False):
        if start_b < end_a:
            raise OverrideError("overlapping corrections")

    offsets, position = [], 0
    for token in texts:
        offsets.append((position, position + len(token)))
        position += len(token) + 1
    first = min(i for i, (a, b) in enumerate(offsets) if b > spans[0][0])
    last = max(i for i, (a, b) in enumerate(offsets) if a < spans[-1][1])
    base, limit = offsets[first][0], offsets[last][1]

    # Walk the touched part of the line and collect (text, rubric) pieces.
    pieces: list[tuple[str, bool | None]] = []
    cursor = base
    for start, end, replacement, rubric in spans:
        if start > cursor:
            pieces.append((text[cursor:start], None))
        if replacement:
            pieces.append((replacement, rubric))
        cursor = end
    if cursor < limit:
        pieces.append((text[cursor:limit], None))

    # Split the touched text into words. The pieces are joined first: a correction often
    # touches the beginning or the end of a word ("скупонени," read for „скупоцени,",
    # a bracket before „Светлости,"), and the rest of that word must stay attached to it.
    # A word takes the rubric flag of the piece its first letter comes from.
    tokens: list[tuple[str, bool | None]] = []
    current, current_rubric = "", None
    for piece, rubric in pieces:
        for character in piece:
            if character == " ":
                if current:
                    tokens.append((current, current_rubric))
                current, current_rubric = "", None
            else:
                if not current:
                    current_rubric = rubric
                current += character
    if current:
        tokens.append((current, current_rubric))
    if not tokens:
        new_words: list[dict] = []
    elif len(tokens) == last - first + 1:
        new_words = [
            {**words[i], "text": token} for i, (token, _) in zip(range(first, last + 1), tokens, strict=True)
        ]
    else:
        # The number of words changed: one was deleted or added. A word that still reads
        # like one of the touched words keeps that word's box, colour and confidence; the
        # others take those of the first replaced word.
        taken: set[int] = set()
        new_words = []
        for token, _ in tokens:
            same = next(
                (i for i in range(first, last + 1) if words[i]["text"] == token and i not in taken), None
            )
            if same is None:
                new_words.append({**words[first], "text": token})
            else:
                taken.add(same)
                new_words.append({**words[same], "text": token})
    for word, (_, rubric) in zip(new_words, tokens, strict=True):
        if rubric is True:
            word["color"], word["red"] = "red", 1.0
        elif rubric is False:
            word["color"], word["red"] = "black", 0.0

    line["words"] = words[:first] + new_words + words[last + 1 :]
    line["text"] = " ".join(w["text"] for w in line["words"])


def apply_overrides(page: dict, overrides: list[dict]) -> dict:
    """Return a corrected copy of an OCR page (contract C2), leaving the original as it is."""
    corrected = copy.deepcopy(page)
    content = [line for line in corrected["lines"] if line["kind"] == "content"]
    by_line: dict[str, list[dict]] = {}
    for override in overrides:
        number = override.get("page")
        if number is not None and number != page["page"]:
            raise OverrideError(
                f"page {page['page']}: a correction is marked for page {number}: {override.get('find')!r}"
            )
        by_line.setdefault(override.get("line"), []).append(override)

    for line_text, group in by_line.items():
        matches = [line for line in content if line["text"] == line_text]
        # ``every`` on a correction says that the line is printed more than once on the
        # page (a refrain) and that all its occurrences get the correction.
        if len(matches) != 1 and not (matches and all(override.get("every") for override in group)):
            raise OverrideError(
                f"page {page['page']}: line {line_text!r} occurs {len(matches)} times, expected exactly once"
            )
        line = matches[0]
        spans, starts = [], []
        for override in group:
            find, replace = override.get("find"), override.get("replace")
            if not isinstance(find, str) or not find or not isinstance(replace, str):
                raise OverrideError(f"page {page['page']}: correction needs 'find' and 'replace': {override}")
            positions, at = [], line["text"].find(find)
            while at != -1:
                positions.append(at)
                at = line["text"].find(find, at + 1)
            # ``occurrence`` says which of several identical passages of the line is meant
            # (counting from 1): two phantom dashes in one line, a word that stands twice.
            occurrence = override.get("occurrence")
            if occurrence is None:
                if len(positions) != 1:
                    raise OverrideError(
                        f"page {page['page']}: {find!r} occurs {len(positions)} times in line {line_text!r}"
                    )
                occurrence = 1
            elif not (isinstance(occurrence, int) and 1 <= occurrence <= len(positions)):
                raise OverrideError(
                    f"page {page['page']}: {find!r} occurs {len(positions)} times in line {line_text!r}"
                    f"; occurrence {occurrence!r} names none of them"
                )
            starts.append(positions[occurrence - 1])
            spans.append((starts[-1], starts[-1] + len(find), replace, override.get("rubric")))
        edges = [0]
        for word in line["words"]:
            edges.append(edges[-1] + len(word["text"]) + 1)
        apply_spans(line, spans)
        # ``left`` says where the replaced words begin on the page. It is for a word the
        # OCR lost at the start of a line: the next word kept its place, and without the
        # right edge the line looks indented, as a new paragraph would be.
        for override, start in zip(group, starts, strict=True):
            left = override.get("left")
            if not isinstance(left, (int, float)) or not override["replace"]:
                continue
            first = sum(1 for edge in edges[1:] if edge <= start)
            line["words"][first]["left"] = left
            line["left"] = min(word["left"] for word in line["words"])
        for other in matches[1:]:
            corrected_line = apply_overrides({"page": page["page"], "lines": [copy.deepcopy(other)]}, group)
            other.update(corrected_line["lines"][0])
    return corrected
