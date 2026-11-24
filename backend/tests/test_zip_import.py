import stat
from zipfile import ZipFile, ZipInfo

import pytest

from app.zip_import import inspect_zip, safe_zip_member


def test_inspect_zip_groups_top_level_courses(tmp_path):
    archive = tmp_path / "学习资料.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("高等数学/第一章.pdf", b"%PDF-1.4")
        zf.writestr("高等数学/课程视频.mp4", b"video")
        zf.writestr("大学英语/单词.md", "# words")

    courses = inspect_zip(archive)

    assert [course.title for course in courses] == ["高等数学", "大学英语"]
    assert courses[0].documents[0].archive_member == "高等数学/第一章.pdf"
    assert courses[0].documents[0].supported is True
    assert courses[0].video_links == []


def test_root_files_use_archive_name_as_course(tmp_path):
    archive = tmp_path / "课堂资料.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("notes.md", "# notes")

    courses = inspect_zip(archive)

    assert courses[0].title == "课堂资料"
    assert courses[0].documents[0].archive_member == "notes.md"


@pytest.mark.parametrize(
    "name",
    [
        "../escape.pdf",
        "/absolute.pdf",
        "a/../../b.pdf",
        "a\\escape.pdf",
    ],
)
def test_zip_path_traversal_is_rejected(tmp_path, name):
    # zipfile normalises backslashes to "/" when writing on Windows, so a
    # backslash member cannot be represented through ZipFile everywhere.
    # Assert the guard directly first, then the archive path where it applies.
    with pytest.raises(ValueError, match="invalid_zip_member"):
        safe_zip_member(name)

    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr(name, b"%PDF-1.4")

    stored = ZipFile(archive).infolist()[0].filename
    if stored == name:
        with pytest.raises(ValueError, match="invalid_zip_member"):
            inspect_zip(archive)
    else:
        # The platform rewrote the name before it reached the archive; the
        # guard itself has still been proven above.
        assert "\\" not in stored


def test_symlink_is_rejected(tmp_path):
    archive = tmp_path / "symlink.zip"
    with ZipFile(archive, "w") as zf:
        item = ZipInfo("course/link.pdf")
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(item, b"target")

    with pytest.raises(ValueError, match="invalid_zip_member"):
        inspect_zip(archive)


def test_encrypted_and_nested_archives_are_rejected(tmp_path):
    encrypted = tmp_path / "encrypted.zip"
    with ZipFile(encrypted, "w") as zf:
        zf.writestr("course/file.pdf", b"%PDF")
    payload = bytearray(encrypted.read_bytes())
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    payload[local + 6] |= 0x1
    payload[central + 8] |= 0x1
    encrypted.write_bytes(payload)

    with pytest.raises(ValueError, match="invalid_zip_member"):
        inspect_zip(encrypted)

    nested = tmp_path / "nested.zip"
    with ZipFile(nested, "w") as zf:
        zf.writestr("course/inner.zip", b"PK")

    with pytest.raises(ValueError, match="nested_archive"):
        inspect_zip(nested)


def test_uncompressed_size_and_member_limits_are_enforced(tmp_path, monkeypatch):
    import app.zip_import as module

    monkeypatch.setattr(module, "MAX_ZIP_MEMBERS", 1)
    archive = tmp_path / "too-many.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("course/a.md", "a")
        zf.writestr("course/b.md", "b")

    with pytest.raises(ValueError, match="too_many_zip_members"):
        inspect_zip(archive)

    monkeypatch.setattr(module, "MAX_ZIP_MEMBERS", 1000)
    monkeypatch.setattr(module, "MAX_ZIP_UNCOMPRESSED_BYTES", 1)
    oversize = tmp_path / "oversize.zip"
    with ZipFile(oversize, "w") as zf:
        zf.writestr("course/a.md", "large")

    with pytest.raises(ValueError, match="zip_too_large"):
        inspect_zip(oversize)
