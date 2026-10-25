"""
Question-paper parser: turns the flat page/line output of the PDF or DOCX
extractors into structured questions (English papers).

Fields read for every question:
    number, section, text, options (A-E), type, correct_option, marks,
    explanation, page, issues
Paper-level fields: title, year, duration, max_marks, preamble.

How it works:
  1. Flatten pages into lines and drop running headers/footers.
  2. Find question starts ("1.", "Q1.", "12)"). The longest run of
     consecutive numbers wins, so numbered instructions at the top
     ("1. Answer all questions") are not mistaken for questions.
  3. Everything up to the next question belongs to that question; the
     options, inline answer, marks and explanation are cut out of it.
  4. Answer keys ("1. B  2. C ...") are read from an "Answer Key" section
     in the same file, or from a separate key file, and matched by number.
  5. A completeness report and per-question issues flag anything that
     wasn't found, so you know what to review.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from utils.json_builder import _normalize

LETTERS = "ABCDE"

Q_START = re.compile(r"^\s*(?:Q(?:uestion)?\s*\.?\s*)?(\d{1,3})\s*[\.\):](?:\s+(.*))?$", re.I)
OPTION_LIKE = re.compile(r"^\s*\(?[A-Ea-e1-5][\)\.]", re.I)
SECTION = re.compile(r"^\s*(?i:part|section)\s*[-–—:\.]?\s*([A-Z]|[IVX]+|\d+)\b(.*)$")
MARKS_EQ = re.compile(r"(\d+)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*=")
MARKS_EACH = re.compile(r"(\d+(?:\.\d+)?)\s*marks?\s*each", re.I)
INLINE_MARKS = re.compile(
    r"[\[\(]\s*(\d+(?:\.\d+)?)\s*(?:marks?|m)\s*[\]\)]|\b(\d+(?:\.\d+)?)\s*marks?\b", re.I
)
INLINE_ANS = re.compile(
    r"^[ \t]*(?:correct\s+)?(?:answer|ans|key)\s*[:\-\.]?\s*\(?\s*([A-Ea-e1-5])\s*\)?\s*(?:[\.\-:].*)?$",
    re.I | re.M,
)
EXPLANATION = re.compile(r"^[ \t]*(?:explanation|solution|sol|rationale)\s*[:\-\.]\s*", re.I | re.M)
KEY_HEAD = re.compile(r"^\s*(?:answer\s*keys?|answers?|key|answer\s*sheet)\s*[:\-]?\s*$", re.I)
LIST_START = re.compile(r"^(?:\d+[\.\)]|[IVXivx]+[\.\)]|\([a-zA-Z0-9]+\)|[-•*]|[A-Z]\.)\s")

OPT_LETTER = re.compile(
    r"(?:(?<![A-Za-z0-9])\(\s*([A-Ea-e])\s*\)|^[ \t]*([A-Ea-e])[\)\.](?=\s))", re.M
)
OPT_DIGIT = re.compile(r"(?<![A-Za-z0-9])\(\s*([1-5])\s*\)")

KEY_PAIR_LETTER = re.compile(r"(?<![\w.])(\d{1,3})\s*[\.\-\):]?\s*\(?\s*([A-Ea-e])\s*\)?(?!\w)")
KEY_PAIR_DIGIT = re.compile(r"(?<![\w.])(\d{1,3})\s*[\.\-\):]\s*\(?\s*([1-5])\s*\)?(?![\w.])")


# ---------------------------------------------------------------- helpers

def _header_footer_noise(pages: List[Dict[str, Any]], edge: int = 2, ratio: float = 0.6) -> set:
    """
    Running headers/footers/page numbers: lines (digits ignored) found among the first or
    last `edge` lines of at least `ratio` of the pages. Only page edges are checked, so
    question text that merely repeats ("Choose the correct answer") is never removed.
    """
    if len(pages) < 3:
        return set()
    counts: Counter = Counter()
    for page in pages:
        texts = [ln.strip() for b in page.get("blocks", []) for ln in b["text"].splitlines() if ln.strip()]
        edges = {_normalize(t) for t in texts[:edge] + texts[-edge:]}
        counts.update(edges)
    cutoff = max(2, int(len(pages) * ratio))
    return {line for line, n in counts.items() if n >= cutoff}


def _flatten(pages: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
    """Pages -> [(page_num, line)], without running headers/footers."""
    noise = _header_footer_noise(pages)
    lines: List[Tuple[int, str]] = []
    for page in pages:
        for block in page.get("blocks", []):
            for raw in block["text"].splitlines():
                line = raw.strip()
                if not line:
                    continue
                if (
                    len(line) <= 80
                    and _normalize(line) in noise
                    and not OPTION_LIKE.match(line)
                    and not Q_START.match(line)
                ):
                    continue
                lines.append((page["page_num"], line))
    return lines


def _join_lines(lines: List[str]) -> str:
    """Join wrapped lines with spaces, but keep list items on their own line."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif LIST_START.match(line) or out.endswith(":"):
            out += "\n" + line
        else:
            out += " " + line
    return re.sub(r"[ \t]+", " ", out).strip()


def _to_letter(value: str) -> str:
    value = value.strip().upper()
    return chr(64 + int(value)) if value.isdigit() else value


def _choose_starts(lines: List[Tuple[int, str]]) -> List[Tuple[int, int, str]]:
    """Pick the longest run of consecutive question numbers (gaps up to 2 allowed)."""
    cands = []
    for idx, (_, line) in enumerate(lines):
        m = Q_START.match(line)
        if m:
            cands.append((idx, int(m.group(1)), (m.group(2) or "").strip()))
    if not cands:
        return []

    by_n: Dict[int, List[int]] = {}
    best: List[Tuple[int, int]] = []
    prev: List[int] = []
    for i, (_, n, _) in enumerate(cands):
        score, p = (1, i), -1
        for d in (1, 2, 3):
            for j in by_n.get(n - d, []):
                cand = (best[j][0] + 1, best[j][1])  # longer chain wins; ties favor the later start
                if cand > score:
                    score, p = cand, j
        best.append(score)
        prev.append(p)
        by_n.setdefault(n, []).append(i)

    end = max(range(len(cands)), key=lambda i: (best[i][0], best[i][1], i))
    chain = []
    while end != -1:
        chain.append(cands[end])
        end = prev[end]
    return chain[::-1]


def _section_info(lines: List[str]) -> Optional[Dict[str, Any]]:
    """If `lines` starts with a Part/Section heading, return its name and per-question marks."""
    m = SECTION.match(lines[0])
    if not m:
        return None
    rest = m.group(2).strip()
    if rest and rest[0].islower():  # "Part III of the Constitution..." is question text, not a heading
        return None
    nearby = " ".join(lines[:3])
    marks = None
    eq = MARKS_EQ.search(nearby)
    each = MARKS_EACH.search(nearby)
    if eq:
        marks = float(eq.group(2))
    elif each:
        marks = float(each.group(1))
    return {"name": lines[0].strip(), "marks": marks}


def _find_option_run(text: str) -> List[Tuple[str, int, int]]:
    """Return [(letter, marker_start, marker_end)] of the last A,B,C... option run."""
    marks = []
    for m in OPT_LETTER.finditer(text):
        letter = (m.group(1) or m.group(2)).upper()
        marks.append((letter, m.start(), m.end()))
    run = _last_run(marks)
    if run:
        return run
    digits = [(chr(64 + int(m.group(1))), m.start(), m.end()) for m in OPT_DIGIT.finditer(text)]
    return _last_run(digits)


def _last_run(marks: List[Tuple[str, int, int]]) -> List[Tuple[str, int, int]]:
    for start in range(len(marks) - 1, -1, -1):
        if marks[start][0] != "A":
            continue
        run = [marks[start]]
        for nxt in marks[start + 1:]:
            if ord(nxt[0]) == ord(run[-1][0]) + 1:
                run.append(nxt)
        if len(run) >= 2:
            return run
    return []


# ------------------------------------------------------------ answer keys

def parse_answer_key(lines: List[str]) -> Dict[int, str]:
    """Read an answer key like '1. B  2. C' or '1-B', '1 (B)', or 'number, letter' on separate lines."""
    text = "\n".join(lines)
    key: Dict[int, str] = {}
    for m in KEY_PAIR_LETTER.finditer(text):
        key.setdefault(int(m.group(1)), m.group(2).upper())
    if len(key) < 3:  # maybe numeric options: "1. 2  2. 4"
        digit_key: Dict[int, str] = {}
        for m in KEY_PAIR_DIGIT.finditer(text):
            digit_key.setdefault(int(m.group(1)), _to_letter(m.group(2)))
        if len(digit_key) > len(key):
            key = digit_key
    if len(key) < 3:  # table cells extracted one per line: "1", "B", "2", "C"
        tokens = re.findall(r"[A-Za-z]+|\d+", text)
        token_key: Dict[int, str] = {}
        for a, b in zip(tokens, tokens[1:]):
            if a.isdigit() and len(b) == 1 and b.upper() in LETTERS:
                token_key.setdefault(int(a), b.upper())
        if len(token_key) > len(key):
            key = token_key
    return key


def key_from_pages(pages: List[Dict[str, Any]]) -> Dict[int, str]:
    """Parse a standalone answer-key file (already run through an extractor)."""
    return parse_answer_key([line for _, line in _flatten(pages)])


# ------------------------------------------------------------- main parser

def _raw_preamble(pages: List[Dict[str, Any]]) -> List[str]:
    """First-page lines before question 1, including running headers (they often hold the title/year)."""
    out: List[str] = []
    for block in pages[0].get("blocks", []) if pages else []:
        for raw in block["text"].splitlines():
            line = raw.strip()
            if Q_START.match(line):
                return out
            if line:
                out.append(line)
    return out


def _paper_info(preamble: List[str]) -> Dict[str, Any]:
    text = "\n".join(preamble)
    year = re.search(r"\b(19|20)\d{2}\b", text)
    duration = re.search(r"\b(?:time|duration)\s*(?:allowed)?\s*[:\-]\s*([^\n]+?)(?=\s{2,}|\s+max|$)", text, re.I)
    max_marks = re.search(r"\bmax(?:imum)?\.?\s*marks?\s*[:\-]?\s*(\d+)", text, re.I)
    return {
        "year": int(year.group(0)) if year else None,
        "duration": duration.group(1).strip() if duration else None,
        "max_marks": int(max_marks.group(1)) if max_marks else None,
        "preamble": preamble[:40],
    }


def _parse_block(lines: List[str]) -> Dict[str, Any]:
    text = "\n".join(lines)
    marks = None
    m = INLINE_MARKS.search(text)
    if m:
        marks = float(m.group(1) or m.group(2))
        text = (text[:m.start()] + text[m.end():]).strip()

    explanation = None
    m = EXPLANATION.search(text)
    if m:
        explanation = _join_lines(text[m.end():].splitlines())
        text = text[:m.start()].rstrip()

    answer = None
    m = INLINE_ANS.search(text)
    if m:
        answer = _to_letter(m.group(1))
        text = (text[:m.start()] + text[m.end():]).strip()

    options: Dict[str, str] = {}
    run = _find_option_run(text)
    if run:
        stem = text[:run[0][1]]
        for k, (letter, _, end) in enumerate(run):
            stop = run[k + 1][1] if k + 1 < len(run) else len(text)
            options[letter] = _join_lines(text[end:stop].splitlines())
    else:
        stem = text

    return {
        "text": _join_lines(stem.splitlines()),
        "options": options,
        "correct_option": answer,
        "marks": marks,
        "explanation": explanation,
    }


def parse_question_paper(
    pages: List[Dict[str, Any]],
    title: str = "Untitled Paper",
    answer_key: Optional[Dict[int, str]] = None,
    default_marks: Optional[float] = None,
) -> Dict[str, Any]:
    """
    pages: output of extract_pdf / extract_docx.
    answer_key: optional {question_number: letter} from a separate key file.
    default_marks: marks to use when neither the question nor its section states any.
    """
    lines = _flatten(pages)
    starts = _choose_starts(lines)
    warnings: List[str] = []

    if not starts:
        return {
            "title": title, "exam_info": {}, "question_count": 0, "questions": [],
            "completeness": summarize([]),
            "warnings": ["No numbered questions were found. If this is a scanned paper, turn on OCR."],
        }

    # answer key section inside the same file
    last_start = starts[-1][0]
    key_idx = next((i for i in range(last_start + 1, len(lines)) if KEY_HEAD.match(lines[i][1])), None)
    end_idx = key_idx if key_idx is not None else len(lines)
    in_file_key = parse_answer_key([ln for _, ln in lines[key_idx + 1:]]) if key_idx is not None else {}

    # preamble: paper info and the section that applies to question 1
    preamble = [ln for _, ln in lines[:starts[0][0]]]
    info = _paper_info(_raw_preamble(pages))
    section = None
    for k in range(len(preamble)):
        found = _section_info(preamble[k:])
        if found:
            section = found

    questions: List[Dict[str, Any]] = []
    for k, (idx, number, rest) in enumerate(starts):
        stop = starts[k + 1][0] if k + 1 < len(starts) else end_idx
        block = ([rest] if rest else []) + [ln for _, ln in lines[idx + 1:stop]]

        next_section = None
        for j in range(len(block)):
            found = _section_info(block[j:])
            if found:
                next_section = found
                block = block[:j]
                break

        parsed = _parse_block(block)
        marks = parsed["marks"]
        if marks is None and section and section["marks"] is not None:
            marks = section["marks"]
        if marks is None:
            marks = default_marks

        questions.append({
            "number": number,
            "section": section["name"] if section else None,
            "text": parsed["text"],
            "options": parsed["options"],
            "type": "mcq" if len(parsed["options"]) >= 2 else "descriptive",
            "correct_option": parsed["correct_option"],
            "marks": marks,
            "explanation": parsed["explanation"],
            "page": lines[idx][0],
            "issues": [],
        })
        if next_section:
            section = next_section

    # answers from key section or key file
    external = dict(in_file_key)
    external.update(answer_key or {})
    for q in questions:
        key_answer = external.get(q["number"])
        if key_answer:
            if q["correct_option"] and q["correct_option"] != key_answer:
                warnings.append(
                    f"Q{q['number']}: inline answer {q['correct_option']} differs from key {key_answer}; kept the key."
                )
            q["correct_option"] = key_answer
    unmatched = sorted(set(external) - {q["number"] for q in questions})
    if unmatched:
        warnings.append(f"Answer key has numbers with no matching question: {unmatched[:15]}")

    _flag_issues(questions, warnings)
    return {
        "title": title,
        "exam_info": info,
        "question_count": len(questions),
        "questions": questions,
        "completeness": summarize(questions),
        "warnings": warnings,
    }


def _flag_issues(questions: List[Dict[str, Any]], warnings: List[str]) -> None:
    numbers = [q["number"] for q in questions]
    if not numbers:
        return
    missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
    if missing:
        warnings.append(f"Question numbers not found: {missing[:20]}{'...' if len(missing) > 20 else ''}")

    mcq_counts = Counter(len(q["options"]) for q in questions if q["type"] == "mcq")
    usual = mcq_counts.most_common(1)[0][0] if mcq_counts else 0
    mostly_mcq = sum(mcq_counts.values()) >= len(questions) / 2

    for q in questions:
        if not q["text"]:
            q["issues"].append("empty question text")
        if mostly_mcq and q["type"] != "mcq":
            q["issues"].append("no options found")
        elif q["type"] == "mcq" and len(q["options"]) < usual:
            q["issues"].append(f"only {len(q['options'])} of {usual} options")
        if q["type"] == "mcq" and any(not v for v in q["options"].values()):
            q["issues"].append("blank option")
        if q["type"] == "mcq" and not q["correct_option"]:
            q["issues"].append("no answer")
        if q["correct_option"] and q["options"] and q["correct_option"] not in q["options"]:
            q["issues"].append(f"answer {q['correct_option']} is not an option")


def summarize(questions: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts of how many questions have each field."""
    return {
        "total": len(questions),
        "with_options": sum(1 for q in questions if len(q.get("options") or {}) >= 2),
        "with_answer": sum(1 for q in questions if q.get("correct_option")),
        "with_marks": sum(1 for q in questions if q.get("marks") is not None),
        "with_section": sum(1 for q in questions if q.get("section")),
        "with_explanation": sum(1 for q in questions if q.get("explanation")),
        "needs_review": sum(1 for q in questions if q.get("issues")),
    }


# ----------------------------------------------- table <-> JSON (review UI)

def questions_to_rows(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for q in questions:
        row = {
            "number": q["number"],
            "section": q.get("section") or "",
            "text": q.get("text") or "",
        }
        for letter in LETTERS:
            row[letter] = (q.get("options") or {}).get(letter, "")
        row.update({
            "correct_option": q.get("correct_option") or "",
            "marks": q.get("marks"),
            "explanation": q.get("explanation") or "",
            "page": q.get("page"),
            "issues": "; ".join(q.get("issues") or []),
        })
        rows.append(row)
    return rows


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def rows_to_questions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rebuild question dicts from the (possibly edited) review table."""
    questions = []
    for row in rows:
        options = {l: _clean(row.get(l)) for l in LETTERS if _clean(row.get(l))}
        marks = _clean(row.get("marks"))
        number = _clean(row.get("number"))
        try:
            marks_val = float(marks) if marks else None
        except ValueError:
            marks_val = None
        q = {
            "number": int(float(number)) if number else None,
            "section": _clean(row.get("section")) or None,
            "text": _clean(row.get("text")),
            "options": options,
            "type": "mcq" if len(options) >= 2 else "descriptive",
            "correct_option": _clean(row.get("correct_option")).upper() or None,
            "marks": marks_val,
            "explanation": _clean(row.get("explanation")) or None,
            "page": int(float(_clean(row.get("page")))) if _clean(row.get("page")) else None,
            "issues": [],
        }
        questions.append(q)
    _flag_issues([q for q in questions if q["number"] is not None], [])
    return questions
