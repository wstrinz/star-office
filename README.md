# Star Office UI

🌐 Language: **English** | [中文](./README.zh.md) | [日本語](./README.ja.md)

![Star Office UI](docs/screenshots/readme-cover-2.jpg)

**A pixel-art office for your AI agent** — real-time visualization of agent state, sessions, background processes, and resource usage. Watch your agent walk to the desk when it's working, lounge on the sofa when idle, and scramble to the server rack when things go wrong.

Supports multi-agent collaboration, three languages (EN/ZH/JP), AI-generated room decoration, exec process monitoring, progressive dashboard, and desktop pet mode.

Best experienced with [OpenClaw](https://github.com/openclaw/openclaw). Also works standalone as a status board driven by any HTTP client.

> Originally created by **[Ring Hyacinth](https://x.com/ring_hyacinth)** and **[Simon Lee](https://x.com/simonxxoo)**, with community contributors [@Zhaohan-Wang](https://github.com/Zhaohan-Wang), [@Jah-yee](https://github.com/Jah-yee), and [@liaoandi](https://github.com/liaoandi).
>
> This fork adds OpenClaw deep integration: live session-based state detection, exec process visibility, contextual status bubbles, progressive dashboard loading, rate limit tracking, and configurable identity. Issues and PRs welcome.

---

## ✨ What It Does

![Star Office UI Preview](docs/screenshots/readme-cover-1.jpg)

### The Pixel Office
Your agent lives in a pixel-art room. Its position and animation reflect what it's actually doing:

| State | Area | When |
|-------|------|------|
| `idle` | 🛋 Sofa (break area) | Waiting for work |
| `writing` | 💻 Desk | Composing responses, writing code |
| `researching` | 💻 Desk | Searching, reading, investigating |
| `executing` | 💻 Desk | Running commands, calling tools |
| `syncing` | 💻 Desk | Pushing data, backing up |
| `error` | 🐛 Server rack | Something broke |

### The Dashboard
Toggle the dashboard panel for operational visibility:
- **Session list** with status dots, token counts, and tap-to-expand details
- **Active threads** showing what the agent is working on across channels
- **Background processes** (exec sessions) with PID, CPU time, memory, and last output
- **Rate limits** with fixed or rolling reset windows, per-provider
- **Cost tracking** with monthly budget and per-model pricing
- **Cron jobs** with recent run history and next-run countdown

### Contextual Status Bubbles
The speech bubble above the agent shows **real context**, not random proverbs:
- `"Active in 3 threads"` — when multitasking
- `"⚡ image-generator is working..."` — when subagents are running
- `"⚙️ benchmark-sweep running (2h 13m)"` — background exec processes
- `"🏖️ Working from the beach"` — travel mode (configurable)
- `"Plenty of capacity today 💪"` — token budget awareness

### Live State Detection
State isn't just push-and-timeout. The backend reads OpenClaw session timestamps to determine activity in real-time:
- Agent starts processing → at the desk within seconds
- Agent finishes → back to the sofa within ~60s
- Subagent running → stays active as long as sessions are updating

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+** (uses `X | Y` union type syntax)
- [OpenClaw](https://github.com/openclaw/openclaw) (optional, for full experience)

### Deploy in 30 seconds

```bash
# Clone
git clone https://github.com/wstrinz/star-office.git
cd star-office

# Install dependencies
python3 -m pip install -r backend/requirements.txt

# Initialize config
cp state.sample.json state.json

# Start
cd backend && python3 app.py
```

Open **http://127.0.0.1:19000** — you should see the pixel office.

### Test state changes

```bash
python3 set_state.py writing "Working on something cool"
python3 set_state.py idle "Standing by"
python3 set_state.py error "Investigating an issue"
```

### With OpenClaw

If you're running OpenClaw, set `OPENCLAW_DIR` and the office will automatically:
- Detect agent state from live session activity
- Show active threads, subagents, and cron jobs
- Monitor background exec processes
- Track token usage and rate limits
- Read your agent's name from `IDENTITY.md`

```bash
export OPENCLAW_DIR=~/.openclaw
cd backend && python3 app.py
```

---

## 🔧 Configuration

See [CONFIG.md](./CONFIG.md) for full configuration reference. Key settings:

### Agent Identity
The office reads your agent's name from `$OPENCLAW_DIR/workspace/IDENTITY.md`. No identity file? Defaults to **"Star"**.

### Environment Variables
Copy `.env.example` → `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENCLAW_DIR` | Path to `.openclaw` data directory | `~/.openclaw` |
| `STAR_OFFICE_ENV` | `production` enables security hardening | `development` |
| `FLASK_SECRET_KEY` | Session secret (required in production) | dev default |
| `STAR_BACKEND_PORT` | Listening port | `19000` |

### Rate Limits
Configure token budget tracking per provider — supports both **fixed reset** (e.g., "Saturday at noon") and **rolling 7-day** windows. See `rate_limits_config.sample.json`.

### Travel Mode
Drop a `travel-mode.json` in your config directory with custom status messages. The agent's bubble will rotate through them. See [CONFIG.md](./CONFIG.md#travel-mode).

### Guest Agents
Share join keys to let other agents appear in your office as guest sprites. See `join-keys.sample.json`.

---

## 📋 Features

### Core
- **6 agent states** with distinct animations and room areas
- **Real-time state** from OpenClaw session timestamps (not just push+timeout)
- **Yesterday memo** — auto-reads recent notes from `memory/*.md`
- **Multi-agent** — guest agents join via join keys, appear as walking sprites
- **Three languages** — EN / ZH / JP, one-click switch
- **Mobile responsive** — works on phone for quick status checks

### Dashboard (OpenClaw integration)
- **Progressive loading** — fast panels render immediately, slow ones stream in
- **Session explorer** — status dots, token counts, model tags, tap-to-expand with cache stats
- **Active threads** — color-coded mini-cards showing what's being worked on
- **Background processes** — detects live exec sessions by scanning JSONL + cross-referencing OS PIDs
- **Rate limits** — per-provider tracking with configurable reset schedules
- **Cost tracking** — monthly budget with per-model pricing breakdown
- **Cron monitor** — job status, recent runs, next-run countdown

### Customization
- **AI room decoration** — Gemini-powered background generation
- **Asset editor** — sidebar for managing sprites, furniture, wall art
- **Configurable identity** — reads agent name from workspace, defaults gracefully
- **Travel mode** — config-driven status messages for working remotely

### Infrastructure
- **Exec process visibility** — background compute jobs show as ⚙️ sprites with PID, CPU, RAM, and last output
- **Contextual status bubbles** — dynamic messages based on real activity, not random strings
- **2-minute rate-limit cache** — first load ~8s, subsequent loads instant
- **Session-based state detection** — no more 5-minute desk-lingering after going quiet

---

## 📡 API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Current agent state (with live session detection) |
| `POST` | `/set_state` | Set agent state manually |
| `GET` | `/agents` | Multi-agent list |
| `GET` | `/yesterday-memo` | Recent notes display |

### OpenClaw Integration

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/openclaw/agents` | Combined agent roster (main + subagents + cron + exec) |
| `GET` | `/openclaw/agent/<name>` | Agent detail (sessions, threads, exec info) |
| `GET` | `/openclaw/sessions` | Active session list with token stats |
| `GET` | `/openclaw/exec-processes` | Live background processes with OS stats |
| `GET` | `/openclaw/rate-limits` | Token usage vs limits (cached) |
| `GET` | `/openclaw/costs` | Cost breakdown by model and time period |
| `GET` | `/openclaw/status-message` | Contextual bubble text based on live state |
| `GET` | `/openclaw/cron` | Cron job status and history |
| `GET` | `/openclaw/usage` | Monthly usage summary |

### Guest Agent Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/join-agent` | Join office with a key |
| `POST` | `/agent-push` | Push guest state update |
| `POST` | `/leave-agent` | Leave office |

---

## 🖥 Desktop Pet (Optional)

The `desktop-pet/` directory provides an Electron wrapper that turns the office into a transparent desktop widget.

```bash
cd desktop-pet && npm install && npm run dev
```

> Experimental — primarily tested on macOS. By [@Zhaohan-Wang](https://github.com/Zhaohan-Wang).

---

## 📁 Project Structure

```text
star-office/
├── backend/              # Flask backend
│   ├── app.py            # Core server + state management
│   ├── openclaw_api.py   # OpenClaw integration endpoints
│   ├── memo_utils.py     # Yesterday memo reader
│   ├── security_utils.py # Auth + session hardening
│   └── requirements.txt
├── frontend/             # Phaser.js pixel office + dashboard
│   ├── index.html        # Main office UI
│   ├── game.js           # Standalone game logic
│   ├── dashboard.js      # Ops dashboard
│   └── layout.js         # Furniture positions
├── desktop-pet/          # Electron desktop wrapper (optional)
├── docs/                 # Documentation + screenshots
├── CONFIG.md             # Configuration reference
├── SKILL.md              # OpenClaw deployment skill
├── set_state.py          # CLI state setter
├── office-agent-push.py  # Guest agent push script
└── LICENSE               # MIT
```

---

## 🎨 Art Assets & License

### Asset Credits
Guest character animations by **LimeZu**: [Animated Mini Characters 2](https://limezu.itch.io/animated-mini-characters-2-platform-free). Please retain attribution in derivative works.

### License
- **Code/logic:** MIT (see [LICENSE](./LICENSE))
- **Art assets:** Non-commercial use only (learning/demo/community)

> For commercial use, replace all art assets with your own originals.

---

## Acknowledgments

- [Ring Hyacinth](https://x.com/ring_hyacinth) & [Simon Lee](https://x.com/simonxxoo) — original Star Office UI
- [OpenClaw](https://github.com/openclaw/openclaw) — the AI agent framework this integrates with
- Community contributors for desktop pet, UI polish, and testing
