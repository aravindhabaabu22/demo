import json

import pandas as pd
import streamlit as st

from extractors.docx_extractor import extract_docx
from extractors.pdf_extractor import extract_pdf
from utils.json_builder import build_structured_json
from utils.ocr_fallback import tesseract_available
from utils.question_parser import (
    key_from_pages, parse_question_paper, questions_to_rows, rows_to_questions, summarize,
)

st.set_page_config(page_title="Book / Question Paper → JSON", page_icon="📚", layout="wide")

st.title("📚 Book / Question paper → structured JSON")
st.caption("Upload a PDF or Word file and get structured JSON. English text only.")

with st.expander("⚠️ Personal use note", expanded=False):
    st.write(
        "This tool is meant for converting books and papers you personally own or have "
        "legal access to, for your own study/reference. It doesn't include any feature "
        "to publish or share the generated JSON with other users."
    )

QP_MODE = "Question paper → questions"
BOOK_MODE = "Book → chapters"
mode = st.radio("What are you converting?", [QP_MODE, BOOK_MODE], horizontal=True)

uploaded_file = st.file_uploader("Upload a file", type=["pdf", "docx"])
key_file = None
if mode == QP_MODE:
    key_file = st.file_uploader(
        "Answer key (optional, if the answers are in a separate file)", type=["pdf", "docx"], key="key_file"
    )

ocr_available = tesseract_available()
ocr_enabled = st.checkbox(
    "Enable OCR fallback for scanned pages",
    value=ocr_available,
    disabled=not ocr_available,
    help=None if ocr_available else "Tesseract isn't installed on this machine, so OCR is unavailable.",
)

if mode == BOOK_MODE:
    size_ratio = st.slider(
        "Heading sensitivity (higher = fewer, bigger headings detected)",
        min_value=1.05, max_value=2.0, value=1.25, step=0.05,
    )
else:
    default_marks = st.number_input(
        "Marks per question when the paper doesn't say (0 = leave blank)", min_value=0.0, value=0.0, step=0.5
    )


def extract(file, progress_callback=None):
    data = file.getvalue()
    ext = file.name.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return extract_pdf(data, ocr_enabled=ocr_enabled, progress_callback=progress_callback)
    if ext == "docx":
        return extract_docx(data)
    raise ValueError("Unsupported file type.")


def show_book_result(result):
    st.success(f"Done. Detected {result['chapter_count']} chapter(s).")
    st.subheader("Preview")
    st.json(result, expanded=False)
    st.download_button(
        "⬇️ Download JSON",
        data=json.dumps(result, indent=2, ensure_ascii=False),
        file_name=f"{result['title']}.json",
        mime="application/json",
    )


def show_paper_result(result):
    qs = result["questions"]
    stats = summarize(qs)
    cols = st.columns(5)
    cols[0].metric("Questions", stats["total"])
    cols[1].metric("With options", stats["with_options"])
    cols[2].metric("With answers", stats["with_answer"])
    cols[3].metric("With marks", stats["with_marks"])
    cols[4].metric("Need review", stats["needs_review"])

    info = {k: v for k, v in result["exam_info"].items() if k != "preamble" and v}
    if info:
        st.caption("Paper info found: " + ", ".join(f"{k} = {v}" for k, v in info.items()))
    for w in result["warnings"]:
        st.warning(w)

    st.subheader("Review and fix")
    st.caption("Edit any cell, add or delete rows, then download. Rows with a note in 'issues' need a look.")
    edited = st.data_editor(
        pd.DataFrame(questions_to_rows(qs)),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        disabled=["issues", "page"],
        column_config={
            "text": st.column_config.TextColumn("text", width="large"),
            "explanation": st.column_config.TextColumn("explanation", width="medium"),
            "correct_option": st.column_config.SelectboxColumn("correct_option", options=["", "A", "B", "C", "D", "E"]),
        },
        key=f"editor_{result['title']}",
    )
    final_qs = rows_to_questions(edited.to_dict("records"))
    final = {
        "title": result["title"],
        "exam_info": result["exam_info"],
        "question_count": len(final_qs),
        "questions": final_qs,
        "completeness": summarize(final_qs),
    }
    st.download_button(
        "⬇️ Download JSON",
        data=json.dumps(final, indent=2, ensure_ascii=False),
        file_name=f"{result['title']}.json",
        mime="application/json",
    )
    with st.expander("Preview JSON"):
        st.json(final, expanded=False)


if uploaded_file is not None:
    title = uploaded_file.name.rsplit(".", 1)[0]
    signature = (mode, uploaded_file.name, uploaded_file.size, key_file.name if key_file else None)
    if st.session_state.get("signature") != signature:
        st.session_state.pop("result", None)  # a new file or mode clears the old result

    if st.button("Convert to JSON", type="primary"):
        progress_bar = st.progress(0.0, text="Starting extraction...")

        def progress_callback(current, total):
            progress_bar.progress(current / total, text=f"Processing page {current}/{total}")

        try:
            with st.spinner("Extracting text..."):
                pages = extract(uploaded_file, progress_callback)
                answer_key = key_from_pages(extract(key_file)) if key_file is not None else None
            progress_bar.progress(1.0, text="Building structured JSON...")
            if mode == QP_MODE:
                result = parse_question_paper(
                    pages, title=title, answer_key=answer_key, default_marks=default_marks or None
                )
            else:
                result = build_structured_json(pages, title=title, size_ratio=size_ratio)
        except Exception as exc:  # corrupt/encrypted files, etc.
            progress_bar.empty()
            st.error(f"Couldn't process this file: {exc}")
            st.stop()
        progress_bar.empty()

        ocr_pages = sum(1 for p in pages if p.get("ocr_used"))
        st.session_state["result"] = result
        st.session_state["signature"] = signature
        st.session_state["ocr_pages"] = ocr_pages

    result = st.session_state.get("result")
    if result is not None and st.session_state.get("signature") == signature:
        empty = result.get("question_count", result.get("chapter_count")) == 0
        if empty:
            st.warning("Nothing was found. If this is a scanned file, enable OCR and try again.")
            for w in result.get("warnings", []):
                st.info(w)
        else:
            if st.session_state.get("ocr_pages"):
                st.info(f"{st.session_state['ocr_pages']} page(s) were read with OCR, so check them in the table.")
            if mode == QP_MODE:
                show_paper_result(result)
            else:
                show_book_result(result)
else:
    st.info("Upload a PDF or DOCX file to begin.")
