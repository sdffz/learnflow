from pathlib import Path

from app.ingestion import TextExtraction
from app.knowledge_domain import CourseCreate, NoteCreate
from app.knowledge_store import KnowledgeStore


def _store(tmp_path, seed_dir: Path | None = None):
    store = KnowledgeStore(
        tmp_path / "learnflow.sqlite3",
        tmp_path / "uploads",
        seed_dir=seed_dir,
    )
    store.initialize()
    return store


def test_store_seeds_default_course_once(tmp_path):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "01-intro.md").write_text(
        "# 人工智能概述\n\n人工智能研究智能体的感知与行动。",
        encoding="utf-8",
    )
    store = _store(tmp_path, seed_dir)

    courses = store.list_courses()
    overview = store.overview()

    assert len(courses) == 1
    assert courses[0].title == "人工智能导论"
    assert courses[0].asset_count == 1
    assert overview.recent_assets[0].title == "人工智能概述"
    assert store.search("感知与行动").items


def test_course_note_and_search_round_trip(tmp_path):
    store = _store(tmp_path)
    course = store.create_course(
        CourseCreate(title="数据结构", description="树与图")
    )
    asset = store.create_note(
        course.id,
        NoteCreate(
            title="BFS",
            content="# 广度优先\n\n广度优先搜索使用队列。",
            tags=["图论", "搜索"],
        ),
    )

    detail = store.get_asset(asset.id)
    results = store.search("队列")

    assert detail is not None
    assert detail.title == "BFS"
    assert detail.knowledge_count == 1
    assert detail.chunks[0].course_title == "数据结构"
    assert results.items[0].asset_id == asset.id
    assert results.total == 1


def test_delete_course_removes_assets_chunks_and_files(tmp_path):
    store = _store(tmp_path)
    course = store.create_course(CourseCreate(title="操作系统"))
    asset = store.create_note(
        course.id,
        NoteCreate(title="进程", content="进程是资源分配单位"),
    )

    store.delete_course(course.id)

    assert store.get_course(course.id) is None
    assert store.get_asset(asset.id) is None
    assert store.search("资源分配").items == []


def test_overview_counts_recent_assets_and_tags(tmp_path):
    store = _store(tmp_path)
    course = store.create_course(CourseCreate(title="编译原理"))
    store.create_note(
        course.id,
        NoteCreate(
            title="语法分析",
            content="语法分析把词法单元组织为语法树。",
            tags=["编译", "语法树"],
        ),
    )

    overview = store.overview()

    assert overview.course_count == 2
    assert overview.asset_count == 1
    assert overview.knowledge_count == 1
    assert overview.recent_assets[0].title == "语法分析"
    assert overview.top_tags[0] in {"编译", "语法树"}


def test_workspace_storage_quota_is_enforced(tmp_path):
    store = KnowledgeStore(
        tmp_path / "learnflow.sqlite3",
        tmp_path / "uploads",
        max_workspace_bytes=10,
    )
    store.initialize()
    course = store.create_course(
        CourseCreate(title="配额测试"),
        "default",
    )

    try:
        store.create_note(
            course.id,
            NoteCreate(title="超限", content="01234567890123456789"),
            "default",
        )
    except ValueError as exc:
        assert str(exc) == "workspace_quota_exceeded"
    else:
        raise AssertionError("quota must be enforced")


def test_external_asset_skips_unchanged_and_updates_changed(tmp_path):
    store = _store(tmp_path)
    course = store.create_course(CourseCreate(title="学习通课程"))
    first_path = tmp_path / "uploads" / "w1" / "first.md"
    first_path.parent.mkdir(parents=True)
    first_path.write_text("第一版", encoding="utf-8")

    first, created = store.upsert_external_asset(
        course_id=course.id,
        workspace_id="default",
        external_source="chaoxing",
        external_id="remote-file-1",
        source_url="https://mooc1.chaoxing.com/file/1",
        checksum="aaa",
        title="讲义",
        original_name="讲义.md",
        mime_type="text/markdown",
        file_relpath="w1/first.md",
        extraction=TextExtraction(text="第一版", status="ready"),
        tags=["学习通"],
        size_bytes=10,
    )
    same, created_again = store.upsert_external_asset(
        course_id=course.id,
        workspace_id="default",
        external_source="chaoxing",
        external_id="remote-file-1",
        source_url="https://mooc1.chaoxing.com/file/1",
        checksum="aaa",
        title="讲义",
        original_name="讲义.md",
        mime_type="text/markdown",
        file_relpath="w1/first.md",
        extraction=TextExtraction(text="第一版", status="ready"),
        tags=["学习通"],
        size_bytes=10,
    )
    second_path = tmp_path / "uploads" / "w1" / "second.md"
    second_path.write_text("第二版", encoding="utf-8")
    changed, created_changed = store.upsert_external_asset(
        course_id=course.id,
        workspace_id="default",
        external_source="chaoxing",
        external_id="remote-file-1",
        source_url="https://mooc1.chaoxing.com/file/1",
        checksum="bbb",
        title="讲义新版",
        original_name="讲义.md",
        mime_type="text/markdown",
        file_relpath="w1/second.md",
        extraction=TextExtraction(text="第二版", status="ready"),
        tags=["学习通", "更新"],
        size_bytes=10,
    )

    assert created is True
    assert created_again is False
    assert same.id == first.id
    assert created_changed is False
    assert changed.id == first.id
    assert changed.title == "讲义新版"
    assert store.search("第二版").items[0].asset_id == first.id
    assert not first_path.exists()


def test_external_asset_is_scoped_by_workspace(tmp_path):
    store = _store(tmp_path)
    course = store.create_course(CourseCreate(title="私有课程"), "w1")

    try:
        store.upsert_external_asset(
            course_id=course.id,
            workspace_id="w2",
            external_source="chaoxing",
            external_id="remote-file-1",
            source_url="https://mooc1.chaoxing.com/file/1",
            checksum="aaa",
            title="讲义",
            original_name="讲义.md",
            mime_type="text/markdown",
            file_relpath=None,
            extraction=TextExtraction(text="正文", status="ready"),
            tags=[],
            size_bytes=2,
        )
    except KeyError as exc:
        assert str(exc) == "'course_not_found'"
    else:
        raise AssertionError("foreign course must be rejected")
