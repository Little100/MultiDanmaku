"use strict";

// ---- State ----
let config = null;
let ws = null;
let token = localStorage.getItem("md_token") || "";
let activeFilter = "all";
const allMessages = [];
const MAX_FEED = 500;

const PLATFORM_DEFAULTS = {
  bilibili: { label: "B站", color: "#00a1d6" },
  douyin:   { label: "抖音", color: "#fe2c55" },
  kuaishou: { label: "快手", color: "#ff6600" },
};

// ---- DOM ----
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ---- Auth ----
async function checkAuth() {
  try {
    const headers = token ? { "X-Token": token } : {};
    const resp = await fetch("/api/config", { headers });
    if (resp.status === 403) {
      showTokenGate();
      return false;
    }
    config = await resp.json();
    if (!config.token || config.token === token) {
      showApp();
      return true;
    }
    showTokenGate();
    return false;
  } catch (e) {
    showTokenGate();
    return false;
  }
}

function showTokenGate() {
  $("#token-gate").style.display = "";
  $("#app").style.display = "none";
}

function showApp() {
  $("#token-gate").style.display = "none";
  $("#app").style.display = "";
  applyConfigToUI(config);
}

function initTokenGate() {
  $("#token-submit").addEventListener("click", submitToken);
  $("#token-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitToken();
  });
}

async function submitToken() {
  const input = $("#token-input");
  const errEl = $("#token-error");
  const t = input.value.trim();
  if (!t) return;
  token = t;
  try {
    const resp = await fetch("/api/config", { headers: { "X-Token": token } });
    if (resp.status === 403) {
      errEl.style.display = "block";
      return;
    }
    config = await resp.json();
    localStorage.setItem("md_token", token);
    errEl.style.display = "none";
    showApp();
  } catch {
    errEl.style.display = "block";
  }
}

// ---- Config <-> UI ----
function applyConfigToUI(cfg) {
  // Platform enable + room
  for (const p of ["bilibili", "douyin", "kuaishou"]) {
    $(`#${p}-enabled`).checked = cfg[p].enabled;
    $(`#${p}-room`).value = cfg[p].room_id;
  }

  // Bilibili Open Live credentials
  $("#bilibili-ol-appid").value = cfg.bilibili.open_live_app_id || "";
  $("#bilibili-ol-key").value = cfg.bilibili.open_live_access_key || "";
  $("#bilibili-ol-secret").value = cfg.bilibili.open_live_access_secret || "";
  $("#bilibili-chat-url").value = cfg.bilibili.chat_url || "";

  // Platform display cards
  for (const p of ["bilibili", "douyin", "kuaishou"]) {
    const card = $(`.display-card[data-platform="${p}"]`);
    if (!card) continue;
    const disp = cfg[p].display || {};
    const def = PLATFORM_DEFAULTS[p];
    card.querySelector(".disp-visible").checked = disp.visible !== false;
    card.querySelector(".disp-label").value = disp.label || "";
    const color = disp.color || def.color;
    card.querySelector(".disp-color").value = color;
    card.querySelector(".disp-color-picker").value = color;
    card.querySelector(".disp-icon").value = disp.icon_url || "";
    // Show preview
    const preview = card.querySelector(".dc-preview");
    if (preview && disp.icon_url) {
      preview.innerHTML = '<img src="' + escA(disp.icon_url) + '" />';
    } else if (preview) {
      preview.innerHTML = "";
    }
  }

  // Display settings
  $("#max-messages").value = cfg.display.max_messages;
  $("#scroll-direction").value = cfg.display.scroll_direction;
  $("#show-platform-badge").checked = cfg.display.show_platform_badge;
  $("#show-timestamp").checked = cfg.display.show_timestamp;
  $("#custom-css").value = cfg.custom_css || "";
  $("#filter-keywords").value = (cfg.display.filter_keywords || []).join("\n");
  $("#blacklist-users").value = (cfg.display.blacklist_users || []).join("\n");
  $("#min-content-length").value = cfg.display.min_content_length;
  $("#token-field").value = cfg.token || "";
}

function collectPlatformDisplay(p) {
  const card = $(`.display-card[data-platform="${p}"]`);
  const def = PLATFORM_DEFAULTS[p];
  return {
    visible: card.querySelector(".disp-visible").checked,
    label: card.querySelector(".disp-label").value.trim() || def.label,
    color: card.querySelector(".disp-color").value.trim() || def.color,
    icon_url: card.querySelector(".disp-icon").value.trim(),
  };
}

function collectConfig() {
  return {
    bilibili: {
      enabled: $("#bilibili-enabled").checked,
      room_id: $("#bilibili-room").value.trim(),
      display: collectPlatformDisplay("bilibili"),
      open_live_app_id: $("#bilibili-ol-appid").value.trim(),
      open_live_access_key: $("#bilibili-ol-key").value.trim(),
      open_live_access_secret: $("#bilibili-ol-secret").value.trim(),
      chat_url: $("#bilibili-chat-url").value.trim(),
    },
    douyin: {
      enabled: $("#douyin-enabled").checked,
      room_id: $("#douyin-room").value.trim(),
      display: collectPlatformDisplay("douyin"),
      open_live_app_id: "",
      open_live_access_key: "",
      open_live_access_secret: "",
    },
    kuaishou: {
      enabled: $("#kuaishou-enabled").checked,
      room_id: $("#kuaishou-room").value.trim(),
      display: collectPlatformDisplay("kuaishou"),
      open_live_app_id: "",
      open_live_access_key: "",
      open_live_access_secret: "",
    },
    custom_css: $("#custom-css").value,
    token: $("#token-field").value.trim(),
    display: {
      max_messages: parseInt($("#max-messages").value, 10) || 200,
      scroll_direction: $("#scroll-direction").value,
      fade_old: false,
      show_platform_badge: $("#show-platform-badge").checked,
      show_timestamp: $("#show-timestamp").checked,
      filter_keywords: splitLines($("#filter-keywords").value),
      blacklist_users: splitLines($("#blacklist-users").value),
      min_content_length: parseInt($("#min-content-length").value, 10) || 0,
    },
  };
}

function splitLines(t) { return t.split("\n").map((s) => s.trim()).filter(Boolean); }

async function saveConfig() {
  try {
    const resp = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Token": token },
      body: JSON.stringify(collectConfig()),
    });
    if (resp.status === 403) {
      showToast("令牌被服务器拒绝", true);
      return;
    }
    config = await resp.json();
    const newToken = config.token || "";
    if (newToken !== token) {
      token = newToken;
      if (token) localStorage.setItem("md_token", token);
      else localStorage.removeItem("md_token");
    }
    showToast("已保存");
  } catch (e) {
    showToast("保存失败", true);
  }
}

// ---- Toast ----
let toastTimer = 0;
function showToast(msg, isError) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "") + " show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 2000);
}

// ---- Navigation ----
function initNav() {
  $$("header nav a").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const page = a.dataset.page;
      $$("header nav a").forEach((x) => x.classList.remove("active"));
      a.classList.add("active");
      $$(".page").forEach((p) => p.classList.remove("active"));
      $(`#page-${page}`).classList.add("active");
    });
  });
}

// ---- WebSocket (feed) ----
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    $("#ws-dot").className = "ws-dot on";
    $("#ws-label").textContent = "已连接";
  };
  ws.onmessage = (e) => {
    try { onLiveEvent(JSON.parse(e.data)); } catch {}
  };
  ws.onclose = () => {
    $("#ws-dot").className = "ws-dot off";
    $("#ws-label").textContent = "重连中...";
    setTimeout(connectWS, 2000);
  };
  ws.onerror = () => ws.close();
}

function getPlatformLabel(platform) {
  if (config && config[platform] && config[platform].display) {
    return config[platform].display.label || PLATFORM_DEFAULTS[platform].label;
  }
  return PLATFORM_DEFAULTS[platform]?.label || platform;
}

function getPlatformColor(platform) {
  if (config && config[platform] && config[platform].display) {
    return config[platform].display.color || PLATFORM_DEFAULTS[platform].color;
  }
  return PLATFORM_DEFAULTS[platform]?.color || "#999";
}

function onLiveEvent(ev) {
  allMessages.push(ev);
  if (allMessages.length > MAX_FEED) allMessages.splice(0, allMessages.length - MAX_FEED);
  if (matchesFilter(ev)) appendFeedItem(ev);
  $("#history-count").textContent = allMessages.length + " 条消息";
}

function matchesFilter(ev) {
  if (activeFilter === "all") return true;
  if (activeFilter === ev.platform) return true;
  if (activeFilter === ev.event_type) return true;
  return false;
}

function appendFeedItem(ev) {
  const list = $("#feed-list");
  const empty = $("#feed-empty");
  if (empty) empty.style.display = "none";
  list.appendChild(buildFeedItem(ev));
  while (list.children.length > MAX_FEED + 1) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

function buildFeedItem(ev) {
  const div = document.createElement("div");
  div.className = "feed-item";
  const d = new Date(ev.timestamp * 1000);
  const ts = pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  const ch = ev.username ? ev.username.charAt(0).toUpperCase() : "?";
  const avHtml = ev.avatar
    ? '<div class="f-avatar"><img src="' + escA(proxyAvatar(ev.avatar)) + '" alt="" /></div>'
    : '<div class="f-avatar">' + esc(ch) + '</div>';
  const badgeLabel = getPlatformLabel(ev.platform);
  const badgeColor = getPlatformColor(ev.platform);
  let typeHtml = "";
  if (ev.event_type !== "danmaku") {
    const tl = { gift: "礼物", enter: "进入", like: "点赞", follow: "关注", system: "系统" };
    typeHtml = '<span class="f-type ' + ev.event_type + '">' + (tl[ev.event_type] || ev.event_type) + '</span>';
  }
  div.innerHTML =
    avHtml +
    '<span class="f-badge" style="background:' + escA(badgeColor) + '">' + esc(badgeLabel) + '</span>' +
    typeHtml +
    '<span class="f-user">' + esc(ev.username) + '</span>' +
    '<span class="f-content">' + esc(ev.content) + '</span>' +
    '<span class="f-time">' + ts + '</span>';
  return div;
}

function renderAll() {
  const list = $("#feed-list");
  list.querySelectorAll(".feed-item").forEach((el) => el.remove());
  const filtered = allMessages.filter(matchesFilter);
  const empty = $("#feed-empty");
  if (filtered.length === 0) {
    if (empty) empty.style.display = "";
  } else {
    if (empty) empty.style.display = "none";
    for (const ev of filtered) list.appendChild(buildFeedItem(ev));
    list.scrollTop = list.scrollHeight;
  }
}

// ---- Filter chips ----
function initChips() {
  $$(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $$(".chip").forEach((c) => c.classList.remove("on"));
      chip.classList.add("on");
      activeFilter = chip.dataset.filter;
      renderAll();
    });
  });
}

// ---- Color picker sync ----
function initColorPickers() {
  $$(".display-card").forEach((card) => {
    const picker = card.querySelector(".disp-color-picker");
    const text = card.querySelector(".disp-color");
    const dot = card.querySelector(".dc-dot");
    picker.addEventListener("input", () => {
      text.value = picker.value;
      dot.style.background = picker.value;
    });
    text.addEventListener("input", () => {
      if (/^#[0-9a-fA-F]{6}$/.test(text.value)) {
        picker.value = text.value;
        dot.style.background = text.value;
      }
    });
  });
}

// ---- Icon upload ----
function initIconUploads() {
  $$(".icon-upload").forEach((input) => {
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file) return;
      const card = input.closest(".display-card");
      const iconInput = card.querySelector(".disp-icon");
      const preview = card.querySelector(".dc-preview");
      const fd = new FormData();
      fd.append("file", file);
      try {
        const resp = await fetch("/api/upload", {
          method: "POST",
          headers: { "X-Token": token },
          body: fd,
        });
        if (resp.ok) {
          const data = await resp.json();
          iconInput.value = data.url;
          preview.innerHTML = '<img src="' + escA(data.url) + '" />';
          showToast("图标已上传");
        } else {
          showToast("上传失败", true);
        }
      } catch {
        showToast("上传失败", true);
      }
    });
  });

  // Show preview for existing icon URLs on load
  $$(".disp-icon").forEach((input) => {
    input.addEventListener("change", () => {
      const card = input.closest(".display-card");
      const preview = card.querySelector(".dc-preview");
      const v = input.value.trim();
      if (v) {
        preview.innerHTML = '<img src="' + escA(v) + '" />';
      } else {
        preview.innerHTML = "";
      }
    });
  });
}

// ---- Test message ----
async function sendTest() {
  const platform = $("#test-platform").value;
  const username = $("#test-username").value.trim() || "测试用户";
  const content = $("#test-content").value.trim() || "这是一条测试消息";
  try {
    const resp = await fetch("/api/test", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": token },
      body: JSON.stringify({ platform, username, content }),
    });
    if (resp.ok) showToast("测试消息已发送");
    else showToast("发送失败", true);
  } catch {
    showToast("发送失败", true);
  }
}

// ---- Overlay ----
async function openOverlay() {
  try {
    const resp = await fetch("/api/overlay", {
      method: "POST",
      headers: { "X-Token": token },
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.new) showToast("悬浮窗已打开");
      else showToast("悬浮窗已在运行");
    } else {
      const err = await resp.json().catch(() => ({}));
      showToast(err.detail || "打开失败", true);
    }
  } catch {
    showToast("打开失败", true);
  }
}

// ---- History ----
async function loadHistory() {
  try {
    const headers = token ? { "X-Token": token } : {};
    const resp = await fetch("/api/history?limit=200", { headers });
    if (resp.ok) {
      const events = await resp.json();
      for (const ev of events) allMessages.push(ev);
      renderAll();
      $("#history-count").textContent = allMessages.length + " 条消息";
    }
  } catch {}
}

async function clearHistory() {
  try {
    await fetch("/api/history/clear", { method: "POST", headers: { "X-Token": token } });
    allMessages.length = 0;
    renderAll();
    $("#history-count").textContent = "";
  } catch {}
}

// ---- Helpers ----
function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }
function escA(s) { return (s ?? "").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function pad(n) { return n < 10 ? "0" + n : "" + n; }
function proxyAvatar(url) { return url && url.includes("hdslb.com") ? "/api/avatar?url=" + encodeURIComponent(url) : url; }

// ---- Init ----
document.addEventListener("DOMContentLoaded", async () => {
  initTokenGate();
  initNav();
  initChips();
  initColorPickers();
  initIconUploads();

  const authed = await checkAuth();
  if (authed) {
    connectWS();
    loadHistory();
    $("#btn-save").addEventListener("click", saveConfig);
    $("#btn-save-display").addEventListener("click", saveConfig);
    $("#btn-clear").addEventListener("click", clearHistory);
    $("#btn-test").addEventListener("click", sendTest);
    $("#btn-open-overlay").addEventListener("click", openOverlay);
    // Refresh config periodically
    setInterval(async () => {
      try {
        const resp = await fetch("/api/config", { headers: { "X-Token": token } });
        if (resp.ok) config = await resp.json();
      } catch {}
    }, 30000);
  }
});
