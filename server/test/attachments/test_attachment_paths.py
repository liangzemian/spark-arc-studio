import pytest

from agents.attachment.storage import compute_attachment_id, get_attachment_root


@pytest.mark.parametrize("value", ["../other", "../../etc", "", "A" * 16, "0" * 15, "0" * 17, None])
def test_attachment_root_rejects_invalid_id(monkeypatch, tmp_path, value):
    monkeypatch.setattr("core.utils.USERDATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        get_attachment_root("1", "demo", value)


def test_attachment_root_accepts_generated_id(monkeypatch, tmp_path):
    monkeypatch.setattr("core.utils.USERDATA_ROOT", str(tmp_path))
    attachment_id = compute_attachment_id("正文")
    assert get_attachment_root("1", "demo", attachment_id) == str(tmp_path / "uid_1" / "projects" / "demo" / ".attachments" / attachment_id)
