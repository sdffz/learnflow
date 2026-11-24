from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation

from app.ingestion import (
    build_knowledge,
    extract_text,
    validate_upload,
)


def test_markdown_text_is_extracted_and_chunked(tmp_path):
    path = tmp_path / "lesson.md"
    path.write_text(
        "# 图论\n\n广度优先搜索使用队列。\n\n深度优先搜索使用栈。",
        encoding="utf-8",
    )

    result = extract_text(path, "text/markdown")
    chunks = build_knowledge(result.text, "图论笔记", ["搜索"])

    assert result.status == "ready"
    assert result.text.startswith("# 图论")
    assert chunks
    assert "广度优先搜索" in chunks[0].excerpt
    assert chunks[0].tags == ["搜索", "图论"]


def test_markdown_metadata_header_is_removed_from_body(tmp_path):
    path = tmp_path / "lesson.md"
    path.write_text(
        "title: 人工智能导论\nmodule: 人工智能基础\nknowledge_point: 概述\n\n人工智能研究智能体。",
        encoding="utf-8",
    )

    result = extract_text(path, "text/markdown")

    assert result.text == "人工智能研究智能体。"


def test_unsupported_extension_is_rejected():
    with pytest.raises(ValueError, match="unsupported_file_type"):
        validate_upload("video.mp4", 10)


def test_oversized_upload_is_rejected():
    with pytest.raises(ValueError, match="file_too_large"):
        validate_upload("notes.md", 26 * 1024 * 1024)


def test_image_without_ocr_runtime_is_preserved(monkeypatch, tmp_path):
    path = tmp_path / "classroom.png"
    path.write_bytes(b"not-real-image")

    def unavailable(_path: Path) -> str:
        raise RuntimeError("tesseract_missing")

    monkeypatch.setattr("app.ingestion._ocr_image", unavailable)

    result = extract_text(path, "image/png")

    assert result.status == "ready_image_only"
    assert result.text == ""
    assert "tesseract_missing" in result.error


def test_docx_paragraphs_and_tables_are_extracted(tmp_path):
    path = tmp_path / "lesson.docx"
    document = Document()
    document.add_paragraph("树是一种层次结构。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "节点"
    table.cell(0, 1).text = "边"
    document.save(path)

    result = extract_text(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    assert result.status == "ready"
    assert "树是一种层次结构" in result.text
    assert "节点 | 边" in result.text


def test_pptx_slide_text_is_extracted(tmp_path):
    path = tmp_path / "slides.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "动态规划"
    text_box = slide.shapes.add_textbox(0, 0, 100, 100)
    text_box.text_frame.text = "状态转移方程"
    presentation.save(path)

    result = extract_text(path, "application/vnd.openxmlformats-officedocument.presentationml.presentation")

    assert result.status == "ready"
    assert "动态规划" in result.text
    assert "状态转移方程" in result.text
