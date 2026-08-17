import time
import wave

from fastapi.testclient import TestClient

from asr_workbench.paths import AppPaths
from asr_workbench.service import create_app


class FakeSenseVoice:
    def generate(self, **_kwargs):
        return [{"text": "本地测试转写结果。"}]


def make_paths(tmp_path):
    root = tmp_path / "application-data"
    for name in ("media", "results", "models"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return AppPaths(root, root / "jobs.sqlite3", root / "media", root / "results", root / "models")


def write_wav(path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 1600)


def test_upload_enters_real_queue_and_persists_txt(tmp_path) -> None:
    source = tmp_path / "sample.wav"
    write_wav(source)
    app = create_app(make_paths(tmp_path))
    app.state.workbench.models._model = FakeSenseVoice()  # noqa: SLF001 - isolate model download.
    with TestClient(app) as client:
        response = client.post("/api/jobs", files={"file": ("样本.wav", source.read_bytes(), "audio/wav")})
        assert response.status_code == 200
        job_id = response.json()["id"]
        final = None
        for _ in range(40):
            final = client.get("/api/jobs/%s" % job_id).json()
            if final["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert final is not None
        assert final["status"] == "completed"
        assert final["transcript"] == "本地测试转写结果。"
        assert client.get("/api/jobs/%s/download" % job_id).status_code == 200


def test_model_not_ready_has_actionable_upload_error(tmp_path) -> None:
    source = tmp_path / "sample.wav"
    write_wav(source)
    app = create_app(make_paths(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/jobs", files={"file": ("sample.wav", source.read_bytes(), "audio/wav")})
    assert response.status_code == 409
    assert "模型" in response.json()["detail"]
