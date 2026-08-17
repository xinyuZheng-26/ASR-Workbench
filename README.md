# ASR Workbench（本地跨平台音视频转写）

ASR Workbench 是一个运行在本机浏览器中的中文音视频转写工作台。它以同一份 Python 代码在 macOS、Windows、Linux 分别构建发行包；**不是一个可跨所有操作系统运行的单一二进制文件**。

默认服务只监听 `127.0.0.1:8765`，启动后自动打开浏览器。没有云端服务、Docker、账号、外部数据库或远程任务队列。首次显式下载模型时需要网络；模型下载并通过加载验证后，转写可在本机离线运行。

## 已实现的行为

- 深蓝中文双栏界面：左侧拖放/选择媒体、文件信息，以及浏览器 `XMLHttpRequest.upload` 的真实上传字节、速度和 ETA；右侧是真实 SQLite 任务、详情、复制文本、导出 TXT 和失败原因。
- 上传进度与推理进度明确分开：上传结束后，模型阶段只显示真实的 `queued`、`running`、`completed`、`failed`，不生成模型百分比。
- 单消费者队列：同一时间只运行一个本地转写任务；应用意外退出时，原 `running` 任务会在下次启动时回到 `queued`。
- `ModelManager` 受控管理 `iic/SenseVoiceSmall` 和 `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`：检查本地缓存、显式下载、实际 `AutoModel` 加载验证、CPU 默认以及可操作错误提示。推理 extra 明确包含 PyTorch 与 Torchaudio。
- 检测 FFmpeg。存在时会把输入安全规范化为单声道 16 kHz WAV；转换失败或缺失 FFmpeg 时会直接把原文件交给 FunASR，不把该回退伪装成已成功转换。
- 媒体、TXT 和 SQLite 均保存到系统的本地应用数据目录，不写入项目目录。

## 本地开发启动

需要 Python 3.9 或更高版本。以下命令使用 `uv`；也可用等价的 `python -m venv` 和 `pip install`。

```bash
cd /path/to/ASR-Workbench
uv sync --extra inference --group dev
uv run asr-workbench
```

浏览器会打开 `http://127.0.0.1:8765`。不希望自动打开浏览器时：

```bash
uv run asr-workbench --no-browser
```

首次启动不自动下载模型。点击页面顶部的“下载并验证模型”后才会下载；成功提示必须同时表示模型已被实际加载。若已经预置模型文件，按钮会显示“加载并验证模型”。

如果只做界面、数据库和测试开发而不下载推理运行时：

```bash
uv sync --group dev
```

这时模型状态会真实地提示缺少推理依赖，不能创建转写任务。

## 本地数据位置

由 `platformdirs` 按系统选择目录，典型位置如下：

| 系统 | 根目录 |
| --- | --- |
| macOS | `~/Library/Application Support/ASR Workbench` |
| Windows | `%LOCALAPPDATA%\\ASR Workbench` |
| Linux | `~/.local/share/ASR Workbench` |

该根目录下包含 `asr-workbench.sqlite3`、`media/`、`results/`、`models/modelscope/`。这些是用户本地数据；删除前请自行备份。项目的 `.gitignore` 不会误收录它们。

## 构建发行包

必须在目标系统上构建对应产物，不能在 macOS 上构建可靠的 Windows 或 Linux 可执行文件。

```bash
# macOS
bash scripts/build_macos.sh

# Linux
bash scripts/build_linux.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

脚本输出在 `dist/`：macOS 为 `ASR-Workbench-macos.zip`，Linux 为 `ASR-Workbench-linux.tar.gz`，Windows 为 `ASR-Workbench-windows.zip`。解压并运行其中的可执行文件即可启动本地服务和浏览器。macOS 首次运行若被 Gatekeeper 拦截，需由发布者完成签名/公证，或由用户按系统安全提示确认；本仓库不绕过系统安全机制。

GitHub Actions 的 [`.github/workflows/release-build.yml`](.github/workflows/release-build.yml) 也会在 macOS、Windows、Linux 的构建矩阵中分别生成对应 artifact。正式发布前应在每个目标系统实际下载并启动该系统的产物。

## 验证

不下载真实模型也可运行状态机、类型限制、SQLite 队列和浏览器上传契约测试：

```bash
uv run ruff check .
uv run pytest
uv run python -m compileall -q asr_workbench tests
uv run asr-workbench --no-browser
```

测试中的小 WAV 使用假模型隔离真实权重下载，但仍验证了真实的上传 API、SQLite 落库、单消费者取队、TXT 落盘和下载路由。它不等同于真实 SenseVoice 识别准确性验证。

若本机已有完整权重和推理依赖，请在界面上运行“加载并验证模型”，再上传一段可公开使用的小样本；只有任务实际进入 `completed` 且结果可复制/下载，才构成真实模型闭环。

## 运行边界

- 默认 CPU，性能取决于本机 CPU、音频时长和模型运行时；不承诺实时速度。
- 本程序不监听局域网地址；命令行也拒绝把 `--host` 改成非 `127.0.0.1`。
- 不上传文件到本项目维护的服务器。模型首次下载的来源由 ModelScope/FunASR 依赖决定；下载完成后正常转写不需要云端。
- 不在应用内删除历史音视频或结果，以避免误删本地数据；用户可在上述应用数据目录自行管理与备份。

## 开源许可提示

本仓库代码采用 MIT 许可（见 `LICENSE`）。FunASR、SenseVoiceSmall、fsmn-vad、FFmpeg 以及其模型权重分别有自己的许可和使用条件；打包或分发权重前请单独核对上游许可。
