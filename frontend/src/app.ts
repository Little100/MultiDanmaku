interface PlatformDisplay {
  visible: boolean;
  label: string;
  color: string;
  icon_url: string;
}

interface LiveEvent {
  platform: "bilibili" | "douyin" | "kuaishou";
  room_id: string;
  event_type: "danmaku" | "gift" | "like" | "enter" | "follow" | "system";
  username: string;
  content: string;
  timestamp: number;
  avatar: string | null;
}

interface PlatformConfig {
  enabled: boolean;
  room_id: string;
  display: PlatformDisplay;
}

interface AppConfig {
  bilibili: PlatformConfig;
  douyin: PlatformConfig;
  kuaishou: PlatformConfig;
  display: {
    max_messages: number;
    scroll_direction: "up" | "down";
    fade_old: boolean;
    show_platform_badge: boolean;
    show_timestamp: boolean;
    filter_keywords: string[];
    blacklist_users: string[];
    min_content_length: number;
    msg_lifetime: number;
  };
  custom_css: string;
  css_template: string;
  token: string;
}

const PLATFORM_DEFAULTS: Record<string, { label: string; color: string }> = {
  bilibili: { label: "B站", color: "#00a1d6" },
  douyin: { label: "抖音", color: "#fe2c55" },
  kuaishou: { label: "快手", color: "#ff6600" },
};

const container = document.getElementById("danmaku-container")!;
const customStyle = document.getElementById("custom-css")!;

let config: AppConfig | null = null;
let ws: WebSocket | null = null;

async function loadConfig(): Promise<void> {
  try {
    const resp = await fetch("/api/config");
    config = (await resp.json()) as AppConfig;
    injectCustomCss(config.custom_css);
    applyScrollDirection();
    const lt = config.display.msg_lifetime ?? 10;
    container.style.setProperty("--msg-lifetime", lt + "s");
  } catch (e) {
    console.error("Failed to load config:", e);
  }
}

function injectCustomCss(css: string): void {
  customStyle.textContent = css;
}

function applyScrollDirection(): void {
  // column-reverse: newest at bottom (DOM[0]), oldest at top (last DOM child)
  container.style.flexDirection = "column-reverse";
}

function getPlatformDisplay(platform: string): PlatformDisplay {
  const defaults = PLATFORM_DEFAULTS[platform] || { label: platform, color: "#999" };
  if (config) {
    const pcfg = (config as any)[platform];
    if (pcfg && pcfg.display) {
      return {
        visible: pcfg.display.visible !== false,
        label: pcfg.display.label || defaults.label,
        color: pcfg.display.color || defaults.color,
        icon_url: pcfg.display.icon_url || "",
      };
    }
  }
  return { visible: true, label: defaults.label, color: defaults.color, icon_url: "" };
}

function shouldShow(event: LiveEvent): boolean {
  if (!config) return true;
  const d = config.display;
  // Check platform visibility
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

function escHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function escAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function proxyAvatar(url: string): string {
  if (url.includes("hdslb.com")) {
    return "/api/avatar?url=" + encodeURIComponent(url);
  }
  return url;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

function createMessageEl(event: LiveEvent): HTMLDivElement {
  const div = document.createElement("div");
  div.className = `msg platform-${event.platform} event-${event.event_type}`;

  // Avatar
  let avatarHtml: string;
  if (event.avatar) {
    avatarHtml = `<span class="avatar"><img src="${escAttr(proxyAvatar(event.avatar))}" alt="" /></span>`;
  } else {
    const ch = event.username ? event.username.charAt(0).toUpperCase() : "?";
    avatarHtml = `<span class="avatar">${escHtml(ch)}</span>`;
  }

  // Platform display config
  const pd = getPlatformDisplay(event.platform);

  // Meta line
  const metaParts: string[] = [];
  if (config?.display.show_platform_badge) {
    if (pd.icon_url) {
      metaParts.push(`<span class="badge badge-${event.platform}"><img src="${escAttr(pd.icon_url)}" alt="${escAttr(pd.label)}" style="height:12px;vertical-align:middle" /></span>`);
    } else {
      const styleAttr = `background:${escAttr(pd.color)}`;
      metaParts.push(`<span class="badge badge-${event.platform}" style="${styleAttr}">${escHtml(pd.label)}</span>`);
    }
  }
  if (event.event_type !== "danmaku") {
    const tl: Record<string, string> = { gift: "礼物", enter: "进入", like: "点赞", follow: "关注", system: "系统" };
    metaParts.push(`<span class="event-type">${tl[event.event_type] ?? event.event_type}</span>`);
  }
  metaParts.push(`<span class="username">${escHtml(event.username)}</span>`);

  // Timestamp
  let tsHtml = "";
  if (config?.display.show_timestamp) {
    const d = new Date(event.timestamp * 1000);
    tsHtml = `<span class="timestamp">${pad(d.getHours())}:${pad(d.getMinutes())}</span>`;
  }

  div.innerHTML =
    avatarHtml +
    `<div class="bubble">` +
      `<div class="meta">${metaParts.join("")}</div>` +
      `<div class="content">${escHtml(event.content)}</div>` +
    `</div>` +
    tsHtml;

  return div;
}

function appendMessage(event: LiveEvent): void {
  if (!shouldShow(event)) return;
  const el = createMessageEl(event);
  // column-reverse: prepend → newest at DOM[0] → visually at BOTTOM
  // Older messages get pushed UP, oldest is the last DOM child (visually at TOP)
  container.insertBefore(el, container.firstChild);
  // Remove oldest (last DOM child = visually at top)
  const max = config?.display.max_messages ?? 200;
  while (container.children.length > max) {
    container.removeChild(container.lastChild as ChildNode);
  }
  // Auto-remove after lifetime
  const lt = (config?.display.msg_lifetime ?? 10) * 1000;
  if (lt > 0) {
    setTimeout(() => {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, lt);
  }
}

function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => console.log("ws connected");
  ws.onmessage = (e: MessageEvent) => {
    try {
      appendMessage(JSON.parse(e.data) as LiveEvent);
    } catch { /* ignore */ }
  };
  ws.onclose = () => {
    console.log("ws closed, reconnecting in 2s...");
    setTimeout(connect, 2000);
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
    if (config && oldScroll !== config.display.scroll_direction) applyScrollDirection();
  }, 30_000);
})();
