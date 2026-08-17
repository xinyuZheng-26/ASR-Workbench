(() => {
  const state = { file: null, jobs: [], selectedId: null, model: null, uploadStartedAt: 0, lastProgress: 0 };
  const $ = (id) => document.getElementById(id);
  const fileInput = $("media-file");
  const startButton = $("start-upload");
  const dropzone = $("dropzone");
  const statusNames = { queued: "排队中", running: "正在转写", completed: "已完成", failed: "失败" };

  function formatBytes(value) {
    if (!Number.isFinite(value)) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0; let number = value;
    while (number >= 1024 && i < units.length - 1) { number /= 1024; i += 1; }
    return `${number >= 10 || i === 0 ? number.toFixed(0) : number.toFixed(1)} ${units[i]}`;
  }
  function formatDuration(seconds) { return seconds == null ? "时长待检测" : `${seconds.toFixed(1)} 秒`; }
  function timeLabel(iso) { return iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false }) : "—"; }
  function escapeHtml(value) { const el = document.createElement("div"); el.textContent = value || ""; return el.innerHTML; }

  function chooseFile(file) {
    state.file = file || null;
    $("file-card").classList.toggle("hidden", !state.file);
    if (state.file) {
      $("file-name").textContent = state.file.name;
      $("file-meta").textContent = `${formatBytes(state.file.size)} · ${state.file.type || "媒体文件"}`;
    }
    startButton.disabled = !state.file || !state.model || !["ready", "available"].includes(state.model.state);
  }
  function setProgress(loaded, total) {
    const percent = total ? Math.min(100, (loaded / total) * 100) : 0;
    const seconds = Math.max(0.001, (Date.now() - state.uploadStartedAt) / 1000);
    const rate = loaded / seconds;
    $("upload-bar").style.width = `${percent}%`;
    $("upload-percent").textContent = `${percent.toFixed(1)}%`;
    $("upload-bytes").textContent = `${formatBytes(loaded)} / ${formatBytes(total)}`;
    $("upload-rate").textContent = `${formatBytes(rate)}/秒`;
    $("upload-eta").textContent = rate > 0 && total > loaded ? `预计 ${Math.ceil((total - loaded) / rate)} 秒` : "即将完成";
  }
  function resetProgress() { $("upload-progress").classList.add("hidden"); $("upload-bar").style.width = "0"; }
  function setUploadMessage(message) { $("upload-label").textContent = message; }

  async function refreshModel() {
    try {
      const response = await fetch("/api/model");
      state.model = await response.json();
      const readable = { checking: "正在检查", missing: "模型未就绪", unavailable: "运行依赖缺失", available: "模型可加载", ready: "模型已就绪", downloading: "正在下载", error: "模型错误" };
      $("model-state").textContent = readable[state.model.state] || state.model.state;
      $("model-message").textContent = state.model.message;
      $("ffmpeg-state").textContent = `FFmpeg：${state.model.ffmpeg_available ? "可用" : "未检测到（将直接尝试原文件）"}`;
      const action = $("model-action");
      action.disabled = state.model.state === "downloading";
      action.textContent = state.model.state === "ready" ? "重新加载验证" : state.model.state === "available" ? "加载并验证模型" : "下载并验证模型";
      chooseFile(state.file);
    } catch (_) { $("model-message").textContent = "无法连接本机服务。"; }
  }
  async function modelAction() {
    const action = $("model-action"); action.disabled = true; action.textContent = "正在处理…";
    try {
      const endpoint = state.model && ["available", "ready"].includes(state.model.state) ? "/api/model/load" : "/api/model/download";
      const response = await fetch(endpoint, { method: "POST" });
      state.model = await response.json();
    } catch (_) { $("model-message").textContent = "模型操作未完成，请检查网络、磁盘空间和本机依赖。"; }
    await refreshModel();
  }

  async function refreshJobs(keepDetail = true) {
    try {
      const response = await fetch("/api/jobs");
      const data = await response.json(); state.jobs = data.jobs || [];
      renderJobs();
      if (keepDetail && state.selectedId) await renderDetail(state.selectedId);
    } catch (_) { /* Browser will retain last visible state while local service restarts. */ }
  }
  function renderJobs() {
    const list = $("job-list"); list.innerHTML = "";
    if (!state.jobs.length) { list.innerHTML = '<div class="empty-list">还没有任务。上传一个音频或视频即可开始。</div>'; return; }
    const template = $("job-template");
    state.jobs.forEach((job) => {
      const node = template.content.firstElementChild.cloneNode(true);
      node.classList.toggle("active", job.id === state.selectedId);
      node.querySelector(".job-status").classList.add(job.status);
      node.querySelector("strong").textContent = job.original_name;
      node.querySelector("small").textContent = `${statusNames[job.status]} · ${timeLabel(job.created_at)}`;
      node.addEventListener("click", () => { state.selectedId = job.id; renderJobs(); renderDetail(job.id); });
      list.appendChild(node);
    });
  }
  async function renderDetail(jobId) {
    const detail = $("job-detail");
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (!response.ok) throw new Error("missing");
      const job = await response.json();
      const isDone = job.status === "completed";
      const isFailed = job.status === "failed";
      const stage = job.status === "queued" ? "任务已写入本机 SQLite 队列，等待唯一的转写工作进程。" : job.status === "running" ? "SenseVoiceSmall 正在进行真实转写；此阶段不提供伪造的模型百分比。" : isDone ? "转写已完成，文本已写入本机结果目录。" : (job.failure_reason || "任务失败，未提供详细原因。");
      detail.innerHTML = `<div class="detail-top"><div><p class="micro-label">任务详情</p><h3>${escapeHtml(job.original_name)}</h3></div><span class="state-pill ${job.status}">${statusNames[job.status]}</span></div><div class="metadata"><span>创建：${escapeHtml(timeLabel(job.created_at))}</span><span>${escapeHtml(formatDuration(job.duration_seconds))}</span><span>ID：${escapeHtml(job.id.slice(0, 8))}</span></div><div class="stage-message ${isFailed ? "failed" : ""}">${escapeHtml(stage)}</div>${isDone ? `<textarea id="transcript" class="transcript" readonly aria-label="转写文本">${escapeHtml(job.transcript || "")}</textarea><div class="detail-actions"><button id="copy-text" class="secondary" type="button">复制文本</button><a class="secondary" href="/api/jobs/${encodeURIComponent(job.id)}/download">导出 TXT</a></div>` : isFailed ? `<div class="detail-actions"><button id="retry-job" class="secondary retry" type="button">重新排队</button></div>` : ""}`;
      const copy = $("copy-text"); if (copy) copy.addEventListener("click", async () => { await navigator.clipboard.writeText($("transcript").value); copy.textContent = "已复制"; });
      const retry = $("retry-job"); if (retry) retry.addEventListener("click", async () => { await fetch(`/api/jobs/${encodeURIComponent(job.id)}/retry`, { method: "POST" }); await refreshJobs(); });
    } catch (_) { detail.innerHTML = '<div class="empty-detail"><h3>任务不可用</h3><p>该任务可能已不存在，或本机服务正在重启。</p></div>'; }
  }
  function upload() {
    if (!state.file) return;
    const xhr = new XMLHttpRequest();
    const form = new FormData(); form.append("file", state.file, state.file.name);
    state.uploadStartedAt = Date.now(); state.lastProgress = 0;
    $("upload-progress").classList.remove("hidden"); setUploadMessage("正在上传到本机服务"); setProgress(0, state.file.size); startButton.disabled = true;
    // This is byte-level browser upload progress, separate from server-side ASR states.
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) { state.lastProgress = event.loaded; setProgress(event.loaded, event.total); } };
    xhr.onerror = () => { setUploadMessage("上传失败：无法连接本机服务"); chooseFile(state.file); };
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        setProgress(state.file.size, state.file.size); setUploadMessage("上传完成，任务已进入本地队列");
        const job = JSON.parse(xhr.responseText); state.selectedId = job.id; await refreshJobs();
      } else {
        let message = "上传失败"; try { message = JSON.parse(xhr.responseText).detail || message; } catch (_) { /* keep generic */ }
        setUploadMessage(`上传失败：${message}`); chooseFile(state.file);
      }
    };
    xhr.open("POST", "/api/jobs"); xhr.send(form);
  }

  fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
  $("clear-file").addEventListener("click", () => { fileInput.value = ""; resetProgress(); chooseFile(null); });
  ["dragenter", "dragover"].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((event) => dropzone.addEventListener(event, (e) => { e.preventDefault(); dropzone.classList.remove("dragging"); }));
  dropzone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
  startButton.addEventListener("click", upload);
  $("refresh-jobs").addEventListener("click", () => refreshJobs());
  $("model-action").addEventListener("click", modelAction);
  refreshModel(); refreshJobs(false); setInterval(() => { refreshModel(); refreshJobs(); }, 2500);
})();
