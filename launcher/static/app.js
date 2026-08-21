/* launcher/static/app.js — 8 步向导：加载后自动环境检测，按状态自动定位下一步 */
"use strict";

const $ = (id) => document.getElementById(id);
const steps = document.querySelectorAll("#steps li");

// 面板索引：0 环境检测 / 1 Torch 安装 / 2 模型下载 / 3 模拟测试 / 4 开始使用
const STEP = { ENV: 0, TORCH: 1, MODELS: 2, SMOKE: 3, READY: 4 };

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
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  return r.json();
}

function renderModels(m) {
  if (!m || !m.files) return;
  const rows = Object.entries(m.files).map(([name, f]) =>
    `${f.ok ? "✅" : "❌"} ${name}  ${f.detail || ""}`).join("\n");
  $("model-list").textContent = rows;
  $("btn-models").textContent = m.ready ? "模型已就绪，重新检测" : "重新检测模型";
}

// 读取 /api/status，按持久化状态自动定位到下一步
async function syncState() {
  const s = await api("/api/status");
  renderModels(s.models || {});
  if (s.torch_ready) $("btn-verify").classList.remove("hidden");
  if (s.smoke_test_passed) { setStep(STEP.READY); return; }
  if ((s.models || {}).ready) { setStep(STEP.SMOKE); return; }
  if (s.torch_ready) { setStep(STEP.MODELS); return; }
  setStep(STEP.TORCH);
}

// 环境检测（加载后自动执行，结果展示后自动进入下一步）
async function runEnv() {
  $("env-result").textContent = "检测中…";
  try {
    const r = await api("/api/env-check", { method: "POST" });
    const d = (r.data || r);
    let msg = d.message || JSON.stringify(d, null, 2);
    if (d.gpu_found === false) {
      msg += "\n⚠️ 未检测到 NVIDIA GPU：界面可正常打开，但修复功能需要 NVIDIA CUDA 显卡。";
    }
    $("env-result").textContent = msg;
  } catch (e) {
    $("env-result").textContent = "环境检测失败：" + e.message;
  }
  await syncState();
}
$("btn-env").onclick = runEnv;

// Torch 安装（轮询进度）
let torchTimer = null;
async function startTorch() {
  $("btn-torch").disabled = true;
  $("torch-bar").style.width = "5%";
  await api("/api/torch/install", { method: "POST" });
  torchTimer = setInterval(async () => {
    const s = await api("/api/torch/status");
    $("torch-log").textContent = s.log || "";
    if (s.status !== "running") {
      clearInterval(torchTimer);
      $("btn-torch").disabled = false;
    }
    if (s.status === "done") {
      $("torch-bar").style.width = "100%";
      $("btn-verify").classList.remove("hidden");
      $("torch-log").textContent += "\n✅ torch 家族安装完成，点击下方「校验通过，下一步」继续。";
    } else if (s.status === "error") {
      $("torch-bar").style.width = "30%";
      $("torch-log").textContent += "\n[失败] " + (s.error || "未知错误") + "，可切换镜像源后重试。";
    }
  }, 1500);
}
$("btn-torch").onclick = async () => {
  await api("/api/torch/mirror", { method: "POST", body: JSON.stringify({ index: $("torch-mirror").value }) });
  startTorch();
};
$("btn-verify").onclick = async () => { await syncState(); };

// 模型
$("btn-models").onclick = async () => { await syncState(); };

// 冒烟测试
let smokeTimer = null;
$("btn-smoke").onclick = async () => {
  $("smoke-result").textContent = "测试进行中（会实际调用 GPU 跑一次修复，约 1-3 分钟），请稍候…";
  await api("/api/smoke-test", { method: "POST" });
  smokeTimer = setInterval(async () => {
    const s = await api("/api/smoke-test/status");
    if (s.status === "running") return;
    clearInterval(smokeTimer);
    const r = s.result || {};
    $("smoke-result").textContent = r.success
      ? "✅ " + r.message + (r.output_path ? "（" + r.output_path + "）" : "")
      : "❌ " + r.message;
    if (r.success) { setStep(STEP.READY); }
  }, 2000);
};

// 开始使用
$("btn-open").onclick = async () => {
  await api("/api/app/start", { method: "POST" });
  await api("/api/app/open", { method: "POST" });
  setStep(STEP.READY);
};

// 初始化：先按持久化状态定位，再自动执行环境检测
(async function init() {
  await syncState();
  await runEnv();
  const rec = await api("/api/models/recommend");
  if (rec && rec.recommended) {
    $("model-recommend").textContent = `推荐主模型：${rec.recommended}（显存 ${rec.vram_gb}GB 档）`;
  }
})();
