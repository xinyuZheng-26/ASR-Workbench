from pathlib import Path


def test_browser_uses_true_xhr_upload_progress_and_no_fake_model_percent() -> None:
    source = (Path(__file__).parents[1] / "asr_workbench" / "web" / "app.js").read_text(encoding="utf-8")
    assert "new XMLHttpRequest()" in source
    assert "xhr.upload.onprogress" in source
    assert "loaded / total" in source
    assert "queued" in source and "running" in source and "completed" in source and "failed" in source
    assert "不提供伪造的模型百分比" in source


def test_frozen_entrypoint_supports_multiprocessing_children() -> None:
    source = (Path(__file__).parents[1] / "run_workbench.py").read_text(encoding="utf-8")
    assert "multiprocessing.freeze_support()" in source
