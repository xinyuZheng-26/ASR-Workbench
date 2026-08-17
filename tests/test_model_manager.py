from asr_workbench.model_manager import ModelManager
from asr_workbench.paths import AppPaths


def make_paths(tmp_path):
    root = tmp_path / "application-data"
    for name in ("media", "results", "models"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return AppPaths(root, root / "jobs.sqlite3", root / "media", root / "results", root / "models")


def test_load_error_survives_status_poll_until_explicit_redetect(monkeypatch, tmp_path) -> None:
    manager = ModelManager(make_paths(tmp_path))
    monkeypatch.setattr(manager, "_model_files_present", lambda: True)
    monkeypatch.setattr(manager, "_funasr_available", lambda: True)

    def fail_load():
        raise RuntimeError("forced load failure")

    monkeypatch.setattr(manager, "_load_model", fail_load)
    result = manager.load_if_available()

    assert result["state"] == "error"
    assert "forced load failure" in result["message"]
    polled = manager.snapshot()
    assert polled["state"] == "error"
    assert "forced load failure" in polled["message"]

    redetected = manager.redetect()
    assert redetected["state"] == "available"


def test_download_error_survives_status_poll(monkeypatch, tmp_path) -> None:
    manager = ModelManager(make_paths(tmp_path))

    def fail_download(_model_id: str) -> None:
        raise RuntimeError("forced download failure")

    monkeypatch.setattr(manager, "_download_model", fail_download)
    result = manager.download_and_validate()

    assert result["state"] == "error"
    assert "forced download failure" in result["message"]
    polled = manager.snapshot()
    assert polled["state"] == "error"
    assert "forced download failure" in polled["message"]


def test_extract_text_removes_sensevoice_control_tokens() -> None:
    result = [{"text": "<|zh|><|NEUTRAL|><|Speech|>你好，世界。"}]

    assert ModelManager._extract_text(result) == "你好，世界。"  # noqa: SLF001 - parser contract.


def test_cached_snapshot_uses_controlled_modelscope_directory(tmp_path) -> None:
    manager = ModelManager(make_paths(tmp_path))
    snapshot = (
        manager.modelscope_cache
        / "models"
        / "iic--SenseVoiceSmall"
        / "snapshots"
        / "revision-a"
    )
    snapshot.mkdir(parents=True)

    assert manager._cached_snapshot("iic/SenseVoiceSmall") == snapshot  # noqa: SLF001
