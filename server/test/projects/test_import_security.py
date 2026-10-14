import asyncio
import errno
import io
import os
import stat
import zipfile

import pytest
from fastapi import UploadFile

from core import utils
from story import routes_project


def _upload(filename, members=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in (members or {"世界观.txt": "旧格式正文"}).items():
            archive.writestr(name, value)
    key = b"x" * routes_project._SPARK_XOR_KEY_LEN
    return UploadFile(filename=filename, file=io.BytesIO(key + routes_project._xor_transform(buffer.getvalue(), key)))


@pytest.mark.parametrize("filename", ["../escape.spark", "..\\escape.spark", "C:\\escape.spark", "C:escape.spark", "/escape.spark", ".._20261015_123000.spark"])
def test_import_rejects_project_path_before_extracting(monkeypatch, tmp_path, filename):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    calls = []
    monkeypatch.setattr(routes_project, "_safe_extract_project_zip", lambda *_: calls.append("extract"))
    monkeypatch.setattr(routes_project.shutil, "move", lambda *_: calls.append("move"))
    monkeypatch.setattr(routes_project.os, "rename", lambda *_: calls.append("rename"))
    response = asyncio.run(routes_project.import_project(_upload(filename), {"user_id": "1"}))
    assert response.status_code == 400
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_import_preserves_old_format_name_and_collision_suffix(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    monkeypatch.setattr("story.importer.import_project_stories_to_db", lambda *_args, **_kwargs: {"status": "fake"})
    first = asyncio.run(routes_project.import_project(_upload("中文项目_20261015_123000.spark"), {"user_id": "1"}))
    second = asyncio.run(routes_project.import_project(_upload("中文项目.spark"), {"user_id": "1"}))
    assert first["projectName"] == "中文项目"
    assert second["projectName"] == "中文项目_1"
    root = tmp_path / "uid_1" / "projects"
    assert sorted(p.name for p in root.iterdir()) == ["中文项目", "中文项目_1"]
    assert (root / "中文项目" / "世界观.txt").read_text(encoding="utf-8") == "旧格式正文"


@pytest.mark.parametrize("member", ["../outside.txt", "..\\outside.txt", "/outside.txt", "C:outside.txt"])
def test_zip_members_cannot_escape_import_directory(tmp_path, member):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "越界")
    with zipfile.ZipFile(buffer) as archive:
        with pytest.raises(ValueError):
            routes_project._safe_extract_project_zip(archive, str(tmp_path))


def test_import_handles_destination_created_concurrently(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    monkeypatch.setattr("story.importer.import_project_stories_to_db", lambda *_args, **_kwargs: {})
    rename = os.rename
    calls = []

    def collide_once(source, target):
        if not calls:
            os.mkdir(target)
            calls.append(target)
            raise FileExistsError(errno.EEXIST, "并发目标已存在")
        rename(source, target)

    monkeypatch.setattr(routes_project.os, "rename", collide_once)
    result = asyncio.run(routes_project.import_project(_upload("项目.spark"), {"user_id": "1"}))
    assert result["projectName"] == "项目_1"
    root = tmp_path / "uid_1" / "projects"
    assert list((root / "项目").iterdir()) == []
    assert (root / "项目_1" / "世界观.txt").is_file()
    assert not list(root.glob(".spark-import-*"))


def test_import_cleans_staging_directory_on_bad_zip(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    upload = UploadFile(filename="项目.spark", file=io.BytesIO(b"x" * (routes_project._SPARK_XOR_KEY_LEN + 5)))
    response = asyncio.run(routes_project.import_project(upload, {"user_id": "1"}))
    assert response.status_code == 400
    assert list((tmp_path / "uid_1" / "projects").iterdir()) == []


def test_zip_rejects_symbolic_link_member(tmp_path):
    buffer = io.BytesIO()
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(link, "../outside")
    with zipfile.ZipFile(buffer) as archive:
        with pytest.raises(ValueError):
            routes_project._safe_extract_project_zip(archive, str(tmp_path))
