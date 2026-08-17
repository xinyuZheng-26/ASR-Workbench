"""SenseVoiceSmall + fsmn-vad lifecycle with a controlled local model cache."""

from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import AppPaths

SENSEVOICE_MODEL = "iic/SenseVoiceSmall"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"


@dataclass
class ModelSnapshot:
    state: str
    message: str
    ffmpeg_available: bool
    model_root: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "message": self.message,
            "ffmpeg_available": self.ffmpeg_available,
            "model_root": self.model_root,
            "models": [SENSEVOICE_MODEL, VAD_MODEL],
        }


class ModelManager:
    """Downloads only when explicitly requested, then validates by actually loading models."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._lock = threading.Lock()
        self._model: Optional[Any] = None
        self._state = "checking"
        self._message = "正在检查本地模型目录。"
        self._configure_modelscope_cache()
        self.refresh()

    @property
    def modelscope_cache(self) -> Path:
        return self.paths.models / "modelscope"

    def _configure_modelscope_cache(self) -> None:
        self.modelscope_cache.mkdir(parents=True, exist_ok=True)
        # ModelScope respects this cache location; all model data stays inside AppPaths.
        os.environ["MODELSCOPE_CACHE"] = str(self.modelscope_cache)

    def refresh(self, *, reset_error: bool = False) -> ModelSnapshot:
        """Explicitly re-detect the local model state.

        Failed downloads and loads are actionable user-facing states. Polling status endpoints
        must not silently replace them with a filesystem-derived state; an explicit retry or
        re-detection is required to clear an error.
        """

        ffmpeg_available = shutil.which("ffmpeg") is not None
        if self._state == "error" and not reset_error:
            return ModelSnapshot(self._state, self._message, ffmpeg_available, str(self.paths.models))
        if self._model is not None:
            self._state = "ready"
            self._message = "SenseVoiceSmall 与 fsmn-vad 已加载，可离线转写。"
        elif not self._model_files_present():
            self._state = "missing"
            self._message = "未找到完整模型。请点击“下载并验证模型”；下载完成后可离线使用。"
        elif not self._funasr_available():
            self._state = "unavailable"
            self._message = "模型文件已存在，但缺少 FunASR 运行依赖。请按文档安装 inference 依赖。"
        else:
            self._state = "available"
            self._message = "检测到模型文件，尚未加载。可点击“加载并验证模型”。"
        return ModelSnapshot(self._state, self._message, ffmpeg_available, str(self.paths.models))

    def snapshot(self) -> Dict[str, Any]:
        # A loaded object is authoritative and cannot coexist with a retained load/download error:
        # failure paths clear ``_model`` before setting ``error``.
        if self._model is not None:
            self._state = "ready"
            self._message = "SenseVoiceSmall 与 fsmn-vad 已加载，可离线转写。"
        return self._current_snapshot().as_dict()

    def redetect(self) -> Dict[str, Any]:
        """Discard a retained error only after an explicit local re-detection request."""

        return self.refresh(reset_error=True).as_dict()

    def download_and_validate(self) -> Dict[str, Any]:
        with self._lock:
            self._state = "downloading"
            self._message = "正在下载 SenseVoiceSmall 与 fsmn-vad；请保持窗口打开。"
            try:
                self._download_model(SENSEVOICE_MODEL)
                self._download_model(VAD_MODEL)
            except ImportError:
                self._state = "unavailable"
                self._message = "缺少 modelscope。请安装：pip install 'asr-workbench[inference]'"
                return self.snapshot()
            except Exception as exc:  # Model hubs expose heterogeneous transport/cache errors.
                self._model = None
                self._state = "error"
                self._message = "模型下载失败：%s" % self._safe_error(exc)
                return self.snapshot()
            try:
                self._model = self._load_model()
                self._state = "ready"
                self._message = "模型下载完成，并已通过实际加载验证。"
            except Exception as exc:  # Model frameworks return heterogeneous exception types.
                self._model = None
                self._state = "error"
                self._message = "模型下载或加载验证失败：%s" % self._safe_error(exc)
            return self.snapshot()

    def _download_model(self, model_id: str) -> None:
        from modelscope.hub.snapshot_download import snapshot_download

        snapshot_download(model_id, cache_dir=str(self.modelscope_cache))

    def _current_snapshot(self) -> ModelSnapshot:
        return ModelSnapshot(
            self._state,
            self._message,
            shutil.which("ffmpeg") is not None,
            str(self.paths.models),
        )

    def load_if_available(self) -> Dict[str, Any]:
        with self._lock:
            if self._model is not None:
                return self.snapshot()
            if not self._model_files_present():
                self._state = "missing"
                self._message = "模型尚未下载。请先点击“下载并验证模型”。"
                return self.snapshot()
            try:
                self._model = self._load_model()
                self._state = "ready"
                self._message = "模型已通过实际加载验证。"
            except Exception as exc:
                self._state = "error"
                self._message = "模型加载验证失败：%s" % self._safe_error(exc)
            return self.snapshot()

    def transcribe(self, audio_path: Path) -> str:
        if self._model is None:
            self.load_if_available()
        if self._model is None:
            raise RuntimeError(self._message)
        result = self._model.generate(
            input=str(audio_path),
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
        return self._extract_text(result)

    def _load_model(self) -> Any:
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError("未安装 FunASR 推理依赖。") from exc
        return AutoModel(
            model=str(self._cached_snapshot(SENSEVOICE_MODEL)),
            vad_model=str(self._cached_snapshot(VAD_MODEL)),
            device="cpu",
            disable_update=True,
        )

    def _cached_snapshot(self, model_id: str) -> Path:
        """Resolve a downloaded ModelScope snapshot without asking the hub again."""

        snapshots = self.modelscope_cache / "models" / model_id.replace("/", "--") / "snapshots"
        candidates = [path for path in snapshots.iterdir() if path.is_dir()] if snapshots.is_dir() else []
        if not candidates:
            raise RuntimeError("模型缓存不完整：%s。请重新下载并验证模型。" % model_id)
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _model_files_present(self) -> bool:
        # ModelScope cache names vary across releases. A conservative search avoids hard-coded
        # cache internals while requiring both requested model identifiers to appear on disk.
        names = {path.name.lower() for path in self.modelscope_cache.rglob("*") if path.is_dir()}
        return any("sensevoice" in name for name in names) and any("fsmn" in name for name in names)

    @staticmethod
    def _funasr_available() -> bool:
        try:
            import funasr  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _extract_text(result: Any) -> str:
        if isinstance(result, list):
            pieces = []
            for item in result:
                if isinstance(item, dict) and item.get("text"):
                    pieces.append(str(item["text"]))
            if pieces:
                return ModelManager._clean_transcript("\n".join(pieces))
        if isinstance(result, dict) and result.get("text"):
            return ModelManager._clean_transcript(str(result["text"]))
        raise RuntimeError("模型未返回可导出的文本结果。")

    @staticmethod
    def _clean_transcript(text: str) -> str:
        """Remove SenseVoice control tokens while preserving the transcribed human text."""

        return re.sub(r"<\|[^|>]+\|>", "", text).strip()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).replace("\n", " ").strip()
        return message[:420] or exc.__class__.__name__
