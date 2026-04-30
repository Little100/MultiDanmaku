# MultiDanmaku

多平台直播弹幕聚合工具，将 B 站、抖音、快手的弹幕/礼物/进入等事件统一显示在一个页面中，适用于 OBS 浏览器源和桌面悬浮窗。
> 抖音没测试 不知道 整个项目99%是llm生成 只有小问题是本人手动修复
## 功能

- 同时接入 B 站、抖音、快手三个平台
- 管理面板配置房间号、显示设置、过滤规则、自定义 CSS
- 平台展示自定义（名称、颜色、图标、可见性）
- 头像显示（B 站头像通过服务端代理，绕过 Referer 检测）
- 上传自定义平台图标
- Token 认证（公网暴露时保护管理接口）
- 桌面悬浮窗（pywebview 原生窗口，置顶、可拖拽、可缩放）
- 发送测试消息验证显示效果

## B 站接入方式

| 方式 | 说明 |
|---|---|
| 数字房间号 | 直连 B 站内部 WebSocket，无需额外配置 |
| 身份码 + 开放平台凭证 | 通过 Open Live API 获取 WebSocket 地址后直连，凭证从 [open-live.bilibili.com](https://open-live.bilibili.com/) 获取 |
| chat.vrp.moe OBS 地址 | 最快捷方式，从 [chat.vrp.moe](https://chat.vrp.moe/) 复制 OBS 地址粘贴即可 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 构建前端（需要 Node.js）
cd frontend
npm install
npm run build
cd ..

# 启动服务
python -m backend
```

服务默认运行在 `http://127.0.0.1:9800`。

| 地址 | 用途 |
|---|---|
| `http://127.0.0.1:9800` | OBS 浏览器源（透明背景） |
| `http://127.0.0.1:9800/admin` | 管理面板 |

## 桌面悬浮窗

需要安装 [pywebview](https://pywebview.flowrl.com/)：

```bash
pip install pywebview
```

在管理面板"展示"页面点击"打开桌面悬浮窗"即可。悬浮窗置顶显示、可拖拽移动、可调整大小。

## 打包为 exe

```bash
pip install pyinstaller
python build.py
```

生成 `dist/MultiDanmaku.exe`，双击运行。

## 命令行参数

```
python -m backend [--host HOST] [--port PORT]
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 绑定地址 |
| `--port` | `9800` | 绑定端口 |

## Token 认证

默认绑定 `127.0.0.1`，无需 Token。暴露到公网时（如 `--host 0.0.0.0`），在管理面板设置 Token，所有配置 API 请求需要携带 `X-Token` 头。OBS 页面和 WebSocket 不受影响。

## 自定义 CSS

内置 LAPLACE Bubble 模板（`frontend/templates/default.css`），可在管理面板"展示"页面的"自定义 CSS"字段覆盖样式。

| 选择器 | 说明 |
|---|---|
| `.msg` | 单条消息行 |
| `.msg .bubble` | 聊天气泡容器 |
| `.msg .avatar` | 用户头像 |
| `.msg .badge` | 平台标签 |
| `.msg .username` | 用户名 |
| `.msg .content` | 消息内容 |
| `.msg .timestamp` | 时间戳 |
| `.msg.platform-bilibili` | B 站平台变体 |
| `.msg.platform-douyin` | 抖音平台变体 |
| `.msg.platform-kuaishou` | 快手平台变体 |
| `.msg.event-gift` | 礼物事件变体 |
| `.msg.event-enter` | 进入事件变体 |
| `.msg.event-like` | 点赞事件变体 |

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/config` | 获取配置 |
| `PUT` | `/api/config` | 更新配置（部分合并） |
| `GET` | `/api/status` | 服务状态 |
| `GET` | `/api/history?limit=N` | 历史消息 |
| `POST` | `/api/history/clear` | 清空历史 |
| `POST` | `/api/test` | 发送测试消息 |
| `POST` | `/api/upload` | 上传图标 |
| `GET` | `/api/avatar?url=...` | 头像代理 |
| `WS` | `/ws` | 实时事件流 |

## 项目结构

```
MultiDanmaku/
├── backend/
│   ├── __main__.py              # 入口
│   ├── app.py                   # FastAPI 服务
│   ├── config.py                # 配置持久化
│   ├── models.py                # LiveEvent / Platform / EventType
│   ├── overlay.py               # 桌面悬浮窗管理
│   ├── _overlay_window.py       # pywebview 窗口进程
│   ├── adapters/
│   │   ├── base.py              # BaseAdapter（自动重连）
│   │   ├── bilibili.py          # B 站（三种接入方式）
│   │   ├── douyin.py            # 抖音 WebSocket
│   │   └── kuaishou.py          # 快手轮询
│   └── services/
│       ├── aggregator.py        # 事件聚合 + WebSocket 广播
│       └── ratelimit.py         # 限流
├── frontend/
│   ├── index.html               # OBS 源页面
│   ├── admin.html               # 管理面板
│   ├── admin.js                 # 管理面板逻辑
│   ├── overlay.html             # 悬浮窗页面
│   ├── src/app.ts               # OBS 源 TypeScript
│   ├── app.js                   # 构建产物
│   └── templates/
│       └── default.css          # LAPLACE Bubble 模板
├── requirements.txt
├── build.py                     # PyInstaller 打包脚本
└── .gitignore
```

## 依赖

```
fastapi>=0.115
uvicorn[standard]>=0.30
aiohttp>=3.10
python-multipart>=0.0.9
pywebview>=5.0
playwright>=1.40
```

B 站 chat.vrp.moe 接入方式需要 Playwright：
```bash
pip install playwright
playwright install chromium
```
