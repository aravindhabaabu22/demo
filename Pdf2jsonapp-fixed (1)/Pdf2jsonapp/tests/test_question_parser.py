import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.question_parser import (
    key_from_pages, parse_answer_key, parse_question_paper, questions_to_rows, rows_to_questions,
)


def _pages(per_page_lines, header="SAMPLE EXAM 2022 - PAPER I"):
    pages = []
    for i, lines in enumerate(per_page_lines, start=1):
        blocks = [{"text": header, "font_size": 10}] + [{"text": t, "font_size": 11} for t in lines]
        blocks.append({"text": f"Page {i}", "font_size": 9})
        pages.append({"page_num": i, "blocks": blocks, "ocr_used": False})
    return pages


def _mcq(n, with_e=True):
    lines = [f"{n}. Which of the following is correct about topic number {n} in the syllabus",
             f"and its related concept {n}?",
             f"(A) first choice for {n}", f"(B) second choice for {n}",
             f"(C) third choice for {n}", f"(D) fourth choice for {n}"]
    if with_e:
        lines.append("(E) Answer not known")
    return lines


def test_full_paper_with_key_section():
    first = ["Time: 3 Hours   Maximum Marks: 200", "Instructions:", "1. Answer all questions",
             "2. Each question carries equal marks", "3. Use blue or black pen",
             "PART A (10 x 2 = 20 Marks)"]
    per_page = [first + _mcq(1) + _mcq(2)]
    n = 3
    while n <= 14:
        per_page.append(_mcq(n) + _mcq(n + 1))
        n += 2
    per_page.append(["Answer Key", "1. B 2. C 3. D 4. A 5. B 6. C 7. D 8. A", "9. B 10. C 11. D 12. A 13. B 14. C"])
    out = parse_question_paper(_pages(per_page), title="sample")

    assert out["question_count"] == 14, out["question_count"]
    assert out["exam_info"]["max_marks"] == 200
    assert out["exam_info"]["year"] == 2022
    q1 = out["questions"][0]
    assert q1["number"] == 1 and q1["text"].startswith("Which of the following")
    assert "related concept 1?" in q1["text"]
    assert list(q1["options"]) == list("ABCDE") and q1["options"]["E"] == "Answer not known"
    assert q1["correct_option"] == "B" and q1["marks"] == 2.0
    assert q1["section"].startswith("PART A")
    assert out["questions"][13]["correct_option"] == "C"
    assert out["completeness"]["with_answer"] == 14 and out["completeness"]["needs_review"] == 0
    assert not out["warnings"], out["warnings"]


def test_inline_options_answers_marks_explanation():
    lines = [
        "1. The capital of India is (A) Mumbai (B) New Delhi (C) Kolkata (D) Chennai [2 marks]",
        "Answer: (B)",
        "Explanation: New Delhi has been the capital since 1911.",
        "2. Who wrote the Constitution draft? (a) Nehru (b) Ambedkar (c) Gandhi (d) Patel",
        "Ans. b",
        "3. Explain the role of the Election Commission in brief.",
    ]
    out = parse_question_paper(_pages([lines]))
    q1, q2, q3 = out["questions"]
    assert q1["options"]["B"] == "New Delhi" and q1["correct_option"] == "B" and q1["marks"] == 2.0
    assert q1["explanation"].startswith("New Delhi")
    assert q2["correct_option"] == "B" and len(q2["options"]) == 4
    assert q3["type"] == "descriptive" and q3["options"] == {}


def test_numeric_options_and_numeric_key():
    lines = []
    for n in range(1, 5):
        lines += [f"{n}. Question text {n} goes here", "(1) one", "(2) two", "(3) three", "(4) four"]
    lines += ["Answers", "1. 2   2. 4   3. 1   4. 3"]
    out = parse_question_paper(_pages([lines]))
    assert out["questions"][0]["options"]["D"] == "four"
    assert [q["correct_option"] for q in out["questions"]] == ["B", "D", "A", "C"]


def test_separate_key_file_and_table_style_key():
    paper = []
    for n in range(1, 6):
        paper += _mcq(n, with_e=False)
    key_pages = _pages([["Q.No", "Ans", "1", "B", "2", "C", "3", "D", "4", "A", "5", "B"]])
    key = key_from_pages(key_pages)
    assert key == {1: "B", 2: "C", 3: "D", 4: "A", 5: "B"}, key
    out = parse_question_paper(_pages([paper]), answer_key=key)
    assert [q["correct_option"] for q in out["questions"]] == ["B", "C", "D", "A", "B"]


def test_warnings_for_missing_pieces():
    lines = _mcq(1) + ["2. A question whose options were lost in the scan"] + _mcq(4)
    out = parse_question_paper(_pages([lines]))
    assert any("not found" in w for w in out["warnings"])
    q2 = next(q for q in out["questions"] if q["number"] == 2)
    assert "no options found" in q2["issues"]
    assert out["completeness"]["needs_review"] >= 2


def test_table_roundtrip():
    lines = _mcq(1) + _mcq(2) + ["Answer Key", "1. A 2. B 3. C"]
    out = parse_question_paper(_pages([lines]))
    rows = questions_to_rows(out["questions"])
    rows[0]["correct_option"] = "d"
    rows[1]["marks"] = float("nan")
    back = rows_to_questions(rows)
    assert back[0]["correct_option"] == "D" and back[1]["marks"] is None
    assert back[0]["options"]["E"] == "Answer not known"


def test_part_of_text_is_not_a_section_heading():
    lines = ["1. Which Article is in", "Part III of the Constitution?", "(A) 14", "(B) 21", "(C) 32", "(D) 44"]
    out = parse_question_paper(_pages([lines]))
    assert out["question_count"] == 1
    assert "Part III" in out["questions"][0]["text"] and len(out["questions"][0]["options"]) == 4
