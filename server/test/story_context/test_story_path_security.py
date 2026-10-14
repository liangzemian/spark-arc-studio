import asyncio

import pytest

from core import utils
from story import routes_files
from story.file_naming import resolve_story_file_path


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path / "userdata"))
    stories = tmp_path / "userdata" / "uid_1" / "projects" / "项目" / "stories"
    stories.mkdir(parents=True)
    outside = stories.parent / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("保留", encoding="utf-8")
    (stories / "正文.md").write_text("正文", encoding="utf-8")
    return stories, outside


@pytest.mark.parametrize("operation", ["save", "create", "delete", "move_source", "move_target", "rename_source", "rename_target", "read", "order"])
def test_file_endpoints_reject_paths_outside_stories(project, operation):
    stories, outside = project
    user = {"user_id": "1"}
    common = {"projectName": "项目", "path": "../outside", "type": "folder"}
    if operation == "save":
        task = routes_files.save_story(routes_files.StoryData(projectName="项目", filename="../outside/secret.md", data="覆盖"), user)
    elif operation == "read":
        task = routes_files.get_file_content("项目", "../outside/secret.md", user)
    elif operation == "order":
        task = routes_files.save_stories_order(routes_files.SaveOrder(projectName="项目", dirPath="../outside", order=["secret"]), user)
    elif operation in {"create", "delete"}:
        task = getattr(routes_files, f"{operation}_file_or_folder")(routes_files.FileOperation(**common), user)
    else:
        name, side = operation.split("_")
        data = routes_files.FileOperation(**common, sourcePath="../outside/secret.md" if side == "source" else "正文.md", targetPath="../outside/new.md" if side == "target" else "新正文.md")
        task = getattr(routes_files, f"{name}_file_or_folder")(data, user)
    response = asyncio.run(task)
    assert response.status_code == 400
    assert (outside / "secret.md").read_text(encoding="utf-8") == "保留"
    assert (stories / "正文.md").read_text(encoding="utf-8") == "正文"
    assert sorted(p.name for p in outside.iterdir()) == ["secret.md"]


@pytest.mark.parametrize("value", ["", ".", "/", "../", "C:\\temp", "\\\\host\\share"])
def test_delete_cannot_remove_stories_root(project, value):
    stories, _ = project
    response = asyncio.run(routes_files.delete_file_or_folder(routes_files.FileOperation(projectName="项目", path=value, type="folder"), {"user_id": "1"}))
    assert response.status_code == 400
    assert stories.is_dir()


def test_resolver_rejects_traversal_before_reading(project):
    stories, _ = project
    with pytest.raises(ValueError):
        resolve_story_file_path(str(stories), "../outside/secret.md")


def test_nested_story_save_and_read_remain_compatible(project):
    stories, _ = project
    user = {"user_id": "1"}
    response = asyncio.run(routes_files.save_story(routes_files.StoryData(projectName="项目", filename="第一卷/初遇.md", data="新正文"), user))
    assert response["success"] is True
    content = asyncio.run(routes_files.get_file_content("项目", "第一卷/初遇.md", user))
    assert content["content"] == "新正文"
    assert len(list((stories / "第一卷").glob("*.md"))) == 1
