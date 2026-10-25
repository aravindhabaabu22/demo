# Book / Question Paper → JSON Converter

Converts PDF or Word (.docx) files into structured JSON, in two modes
(English text only):

- **Question paper → questions:** reads every question with its number,
  text, options (A to E), correct answer, marks, section, and explanation,
  and flags anything it couldn't find.
- **Book → chapters:** detected chapters with page-level text.

Both modes have an OCR fallback for scanned pages.

## Question paper output

```json
{
  "title": "TNPSC-2022-paper-1",
  "exam_info": { "year": 2022, "duration": "3 Hours", "max_marks": 200 },
  "question_count": 100,
  "questions": [
    {
      "number": 1,
      "section": "PART A (10 x 2 = 20 Marks)",
      "text": "Which of the following ...?",
      "options": { "A": "...", "B": "...", "C": "...", "D": "...", "E": "Answer not known" },
      "type": "mcq",
      "correct_option": "B",
      "marks": 2.0,
      "explanation": null,
      "page": 1,
      "issues": []
    }
  ],
  "completeness": { "total": 100, "with_options": 100, "with_answer": 100,
                    "with_marks": 100, "with_section": 100, "with_explanation": 0, "needs_review": 0 }
}
```

How each field is found:

- **Question numbers:** `1.`, `Q1.`, `12)`. The longest run of consecutive
  numbers wins, so numbered instructions at the top are ignored.
- **Options:** `(A) ... (B) ...` on one line or separate lines, `A)` / `A.`
  at line start, or `(1) ... (4)`. Numeric options are saved as A to D.
- **Answers:** a line like `Answer: B` or `Ans. (b)` under the question, an
  *Answer Key* section at the end of the file (`1. B  2. C ...`), or a separate
  key file uploaded in the app. The key wins if it disagrees with an inline answer.
- **Marks:** `[2 marks]` on the question, otherwise the section heading
  (`PART A (10 x 2 = 20 Marks)` or `2 marks each`), otherwise the default you enter.
- **Sections:** lines starting `Part A`, `Section II`, and so on.
- **Explanation:** text after `Explanation:`, `Solution:`, or `Rationale:`.
- **Paper info:** year, duration, and maximum marks from the first page.
- **Issues:** missing numbers, no options, fewer options than usual, no
  answer, or an answer that isn't one of the options. Fix these in the
  review table before downloading.

Not read: diagrams and images inside questions, and "match the following"
tables (their text is kept inside the question text, in reading order).

## Book output shape

```json
{
  "title": "My Book",
  "chapter_count": 5,
  "chapters": [
    {
      "heading": "Chapter 1: Introduction",
      "pages": [
        { "page_num": 3, "text": "...", "ocr_used": false }
      ]
    }
  ]
}
```

## Project layout

```
streamlit_app.py            # Streamlit UI
extractors/pdf_extractor.py # PDF -> pages of text lines + font sizes (OCR fallback)
extractors/docx_extractor.py# DOCX -> pseudo-pages, headings from Word styles
utils/json_builder.py       # pages -> chapters (heading detection, header/footer removal)
utils/question_parser.py    # pages -> questions, options, answers, marks, sections
utils/ocr_fallback.py       # Tesseract OCR for scanned pages
tests/                      # quick checks (python -m pytest tests)
```

## Setup

```bash
pip install -r requirements.txt
# OCR needs the Tesseract program too:
#   Ubuntu/Debian: sudo apt install tesseract-ocr
#   macOS:         brew install tesseract
#   Windows:       install from https://github.com/UB-Mannheim/tesseract/wiki
streamlit run streamlit_app.py
```

On Streamlit Community Cloud, `packages.txt` installs Tesseract automatically.

## How chapters are detected

- **PDF:** lines in a noticeably larger font than the body text (adjust with
  the *Heading sensitivity* slider) and short enough to be a title start a
  new chapter. Repeated running headers, footers and page numbers are
  ignored. Back-to-back heading lines are merged.
- **DOCX:** paragraphs styled *Title* or *Heading 1* start a new chapter.
  Pages come from page breaks in the file; a document with none is one page.
- **OCR pages** have no font information, so headings can't be detected on
  them; their text is attached to the current chapter.

## Notes

- Use this only for books you own or have legal access to.
- Password-protected PDFs must be unlocked first.
