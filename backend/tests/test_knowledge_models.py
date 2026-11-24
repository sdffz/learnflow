import pytest
from pydantic import ValidationError

from app.knowledge_domain import CourseCreate, excerpt, normalize_tags


def test_course_create_trims_title_and_description():
    course = CourseCreate(
        title="  数据结构  ",
        description="  链表、树、图  ",
    )

    assert course.title == "数据结构"
    assert course.description == "链表、树、图"


def test_course_create_rejects_whitespace_only_title():
    with pytest.raises(ValidationError):
        CourseCreate(title="   ")


def test_tags_are_trimmed_deduplicated_and_limited():
    assert normalize_tags([" AI ", "ai", "", "图论", "图论"]) == ["AI", "图论"]


def test_excerpt_collapses_whitespace_and_limits_length():
    assert excerpt("  第一行\n\n第二行  ", 5) == "第一行 第"
