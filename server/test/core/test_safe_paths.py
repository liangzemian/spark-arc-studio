from pathlib import Path
import os
import subprocess

import pytest

from core import utils


def _directory_link(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


@pytest.mark.parametrize("value", ["../secret", "a/../../secret", "/secret", "\\secret", "C:\\secret", "C:secret", "a:stream", "a\x00b", "", ".", "a/.."])
def test_safe_join_rejects_unsafe_relative_paths(tmp_path, value):
    with pytest.raises(ValueError):
        utils.safe_join(str(tmp_path), value)


def test_safe_join_preserves_nested_unicode_names(tmp_path):
    assert utils.safe_join(str(tmp_path), "第一卷\\章节（初遇）.md") == str(tmp_path / "第一卷" / "章节（初遇）.md")
    assert utils.safe_join(str(tmp_path), "", allow_root=True) == str(tmp_path)


def test_safe_join_rejects_link_outside_root(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _directory_link(root / "link", outside)
    with pytest.raises(ValueError):
        utils.safe_join(str(root), "link/secret.md")


@pytest.mark.parametrize("value", ["../secret.md", "C:secret.md", "..", "a/../../secret.md"])
def test_lorebook_path_is_confined_to_project(monkeypatch, tmp_path, value):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        utils.get_project_lorebook_path("1", "项目", value)


def test_project_path_rejects_link_to_another_user(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    root = Path(utils.get_user_projects_root("1"))
    root.mkdir(parents=True)
    outside = tmp_path / "another_user"
    outside.mkdir()
    _directory_link(root / "项目", outside)
    with pytest.raises(ValueError):
        utils.get_project_path("1", "项目")


def test_stories_root_cannot_link_outside_project(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "USERDATA_ROOT", str(tmp_path))
    project = Path(utils.get_project_path("1", "项目"))
    project.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    _directory_link(project / "stories", outside)
    with pytest.raises(ValueError):
        utils.get_project_stories_path("1", "项目")
