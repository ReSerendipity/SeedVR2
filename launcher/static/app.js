/* launcher/static/app.js — 8 步向导轮询后端 */
"use strict";

const $ = (id) => document.getElementById(id);
const steps = document.querySelectorAll("#steps li");

function setStep(idx) {
  steps.forEach((el, i) => {
    el.classList.toggle("active", i === idx);
    el.classList.toggle("done", i < idx);
  });
  document.querySelectorAll(".panel").forEach((p, i) => {
    p.classList.toggle("hidden", i !== idx);
  });
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}

async function refreshStatus() {
  const s = await api("/api/status");
  const state = s.state || {};
  if (state.torch_ready) { $("btn-verify").classList.remove("hidden"); }
  const models = s.models || {};
  renderModels(models);
  if (state.smoke_test_passed) setStep(4);
}

function renderModels(m) {
  if (!m.files) return;
  const rows = Object.entries(m.files).map(([name, f]) =>
    `${f.ok ? "✅" : "❌"} ${name}  ${f.detail || ""}`).join("\n");
  $("model-list").textContent = rows;
}

// 环境检测
async function runEnv() {
  $("env-result").textContent = "检测中…";
  const r = await api("/api/env-check", { method: "POST" });
  const d = (r.data || r);
  $("env-result").textContent = d.message || JSON.stringify(d, null, 2);
  setStep(1);
}
$("btn-env").onclick = runEnv;

// Torch 安装（轮询进度）
let torchTimer = null;
async function startTorch() {
  $("btn-torch").disabled = true;
  await api("/api/torch/install", { method: "POST" });
  torchTimer = setInterval(async () => {
    const s = await api("/api/torch/status");
    $("torch-log").textContent = s.log || "";
    if (s.status === "running") return;
    clearInterval(torchTimer);
    $("btn-torch").disabled = false;
    if (s.status === "done") {
      $("torch-bar").style.width = "100%";
      $("btn-verify").classList.remove("hidden");
      setStep(2);
    } else {
      $("torch-bar").style.width = "30%";
      $("torch-log").textContent += "\n[失败] " + (s.error || "未知错误") + "，可换镜像源重试。";
    }
  }, 1500);
}
$("btn-torch").onclick = async () => {
  await api("/api/torch/mirror", { method: "POST", body: JSON.stringify({ index: $("torch-mirror").value }) });
  startTorch();
};
$("btn-verify").onclick = async () => { await refreshStatus(); setStep(2); };

// 模型
$("btn-models").onclick = async () => { await refreshStatus(); };
refreshStatus().then(async () => {
  const rec = await api("/api/models/recommend");
  $("model-recommend").textContent = `推荐主模型：${rec.recommended}（显存 ${rec.vram_gb}GB 档）`;
});

// 冒烟测试
let smokeTimer = null;
$("btn-smoke").onclick = async () => {
  $("smoke-result").textContent = "测试进行中，请稍候…";
  await api("/api/smoke-test", { method: "POST" });
  smokeTimer = setInterval(async () => {
    const s = await api("/api/smoke-test/status");
    if (s.status === "running") return;
    clearInterval(smokeTimer);
    const r = s.result || {};
    $("smoke-result").textContent = r.success ? "✅ " + r.message + "（" + (r.output_path || "") + "）" : "❌ " + r.message;
    if (r.success) setStep(4);
  }, 2000);
};

// 开始使用
$("btn-open").onclick = async () => {
  await api("/api/app/start", { method: "POST" });
  await api("/api/app/open", { method: "POST" });
  setStep(5);
};
