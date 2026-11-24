from __future__ import annotations

import hashlib
import stat
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .ingestion import SUPPORTED_EXTENSIONS
from .learning_domain import PreviewCourse, PreviewFile

MAX_ZIP_MEMBERS = 1_000
MAX_ZIP_UNCOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024
MAX_ZIP_FILE_BYTES = 100 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".m3u8", ".flv", ".avi", ".mov", ".mkv", ".webm"}
NESTED_ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


def safe_zip_member(name: str) -> PurePosixPath:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError("invalid_zip_member")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid_zip_member")
    return path


def inspect_zip(path: Path) -> list[PreviewCourse]:
    if path.suffix.casefold() != ".zip":
        raise ValueError("unsupported_zip_type")
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise ValueError("too_many_zip_members")
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("zip_too_large")
            grouped: OrderedDict[str, list[tuple[str, object]]] = OrderedDict()
            for info in infos:
                if info.is_dir():
                    continue
                member = safe_zip_member(info.filename)
                if info.flag_bits & 0x1:
                    raise ValueError("invalid_zip_member")
                file_type = (info.external_attr >> 16) & 0o170000
                if file_type == stat.S_IFLNK:
                    raise ValueError("invalid_zip_member")
                suffix = Path(member.name).suffix.casefold()
                if suffix in NESTED_ARCHIVE_EXTENSIONS:
                    raise ValueError("nested_archive")
                if suffix in VIDEO_EXTENSIONS:
                    continue
                if len(member.parts) == 1:
                    course_title = path.stem or "导入资料"
                else:
                    course_title = member.parts[0]
                grouped.setdefault(course_title, []).append(
                    (str(member), info)
                )
            courses: list[PreviewCourse] = []
            for title, members in grouped.items():
                documents: list[PreviewFile] = []
                for member_name, info in members:
                    suffix = Path(member_name).suffix.casefold()
                    supported = (
                        suffix in SUPPORTED_EXTENSIONS
                        and info.file_size <= MAX_ZIP_FILE_BYTES
                    )
                    reason = None
                    if suffix not in SUPPORTED_EXTENSIONS:
                        reason = "unsupported_file_type"
                    elif info.file_size > MAX_ZIP_FILE_BYTES:
                        reason = "file_too_large"
                    documents.append(
                        PreviewFile(
                            id=hashlib.sha256(
                                member_name.encode("utf-8")
                            ).hexdigest()[:24],
                            name=Path(member_name).name[:180],
                            extension=suffix,
                            size_bytes=info.file_size,
                            supported=supported,
                            excluded_reason=reason,
                            archive_member=member_name,
                        )
                    )
                if documents:
                    courses.append(
                        PreviewCourse(
                            id=hashlib.sha256(title.encode("utf-8")).hexdigest()[:24],
                            title=title[:120],
                            documents=documents,
                        )
                    )
            return courses
    except BadZipFile as exc:
        raise ValueError("invalid_zip_file") from exc
