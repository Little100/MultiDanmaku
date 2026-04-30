"use strict";
(() => {
  // src/app.ts
  var PLATFORM_DEFAULTS = {
    bilibili: { label: "B\u7AD9", color: "#00a1d6" },
    douyin: { label: "\u6296\u97F3", color: "#fe2c55" },
    kuaishou: { label: "\u5FEB\u624B", color: "#ff6600" }
  };
  var container = document.getElementById("danmaku-container");
  var customStyle = document.getElementById("custom-css");
  var config = null;
  var ws = null;
  async function loadConfig() {
    try {
      const resp = await fetch("/api/config");
      config = await resp.json();
      injectCustomCss(config.custom_css);
      applyScrollDirection(config.display.scroll_direction);
    } catch (e) {
      console.error("Failed to load config:", e);
    }
  }
  function injectCustomCss(css) {
    customStyle.textContent = css;
  }
  function applyScrollDirection(direction) {
    container.style.flexDirection = direction === "down" ? "column" : "column-reverse";
  }
  function getPlatformDisplay(platform) {
    const defaults = PLATFORM_DEFAULTS[platform] || { label: platform, color: "#999" };
    if (config) {
      const pcfg = config[platform];
      if (pcfg && pcfg.display) {
        return {
          visible: pcfg.display.visible !== false,
          label: pcfg.display.label || defaults.label,
          color: pcfg.display.color || defaults.color,
          icon_url: pcfg.display.icon_url || ""
        };
      }
    }
    return { visible: true, label: defaults.label, color: defaults.color, icon_url: "" };
  }
  function shouldShow(event) {
    if (!config) return true;
    const d = config.display;
    const pd = getPlatformDisplay(event.platform);
    if (!pd.visible) return false;
    if (d.blacklist_users.includes(event.username)) return false;
    if (d.min_content_length > 0 && event.content.length < d.min_content_length) return false;
    if (d.filter_keywords.length > 0) {
      const lower = event.content.toLowerCase();
      if (d.filter_keywords.some((kw) => lower.includes(kw.toLowerCase()))) return false;
    }
    return true;
  }
  function escHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
  function escAttr(s) {
    return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function proxyAvatar(url) {
    if (url.includes("hdslb.com")) {
      return "/api/avatar?url=" + encodeURIComponent(url);
    }
    return url;
  }
  function pad(n) {
    return n < 10 ? `0${n}` : `${n}`;
  }
  function createMessageEl(event) {
    const div = document.createElement("div");
    div.className = `msg platform-${event.platform} event-${event.event_type}`;
    let avatarHtml;
    if (event.avatar) {
      avatarHtml = `<span class="avatar"><img src="${escAttr(proxyAvatar(event.avatar))}" alt="" /></span>`;
    } else {
      const ch = event.username ? event.username.charAt(0).toUpperCase() : "?";
      avatarHtml = `<span class="avatar">${escHtml(ch)}</span>`;
    }
    const pd = getPlatformDisplay(event.platform);
    const metaParts = [];
    if (config?.display.show_platform_badge) {
      if (pd.icon_url) {
        metaParts.push(`<span class="badge badge-${event.platform}"><img src="${escAttr(pd.icon_url)}" alt="${escAttr(pd.label)}" style="height:12px;vertical-align:middle" /></span>`);
      } else {
        const styleAttr = `background:${escAttr(pd.color)}`;
        metaParts.push(`<span class="badge badge-${event.platform}" style="${styleAttr}">${escHtml(pd.label)}</span>`);
      }
    }
    if (event.event_type !== "danmaku") {
      const tl = { gift: "\u793C\u7269", enter: "\u8FDB\u5165", like: "\u70B9\u8D5E", follow: "\u5173\u6CE8", system: "\u7CFB\u7EDF" };
      metaParts.push(`<span class="event-type">${tl[event.event_type] ?? event.event_type}</span>`);
    }
    metaParts.push(`<span class="username">${escHtml(event.username)}</span>`);
    let tsHtml = "";
    if (config?.display.show_timestamp) {
      const d = new Date(event.timestamp * 1e3);
      tsHtml = `<span class="timestamp">${pad(d.getHours())}:${pad(d.getMinutes())}</span>`;
    }
    div.innerHTML = avatarHtml + `<div class="bubble"><div class="meta">${metaParts.join("")}</div><div class="content">${escHtml(event.content)}</div></div>` + tsHtml;
    return div;
  }
  function appendMessage(event) {
    if (!shouldShow(event)) return;
    const el = createMessageEl(event);
    container.appendChild(el);
    const max = config?.display.max_messages ?? 200;
    while (container.children.length > max) {
      container.removeChild(container.children[0]);
    }
    container.scrollTop = container.scrollHeight;
  }
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => console.log("ws connected");
    ws.onmessage = (e) => {
      try {
        appendMessage(JSON.parse(e.data));
      } catch {
      }
    };
    ws.onclose = () => {
      console.log("ws closed, reconnecting in 2s...");
      setTimeout(connect, 2e3);
    };
    ws.onerror = () => ws?.close();
  }
  (async () => {
    await loadConfig();
    connect();
    setInterval(async () => {
      const oldCss = config?.custom_css;
      const oldScroll = config?.display.scroll_direction;
      await loadConfig();
      if (config && oldCss !== config.custom_css) injectCustomCss(config.custom_css);
      if (config && oldScroll !== config.display.scroll_direction) applyScrollDirection(config.display.scroll_direction);
    }, 3e4);
  })();
})();
//# sourceMappingURL=app.js.map
