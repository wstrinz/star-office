# Configuration Guide

Star Office UI is designed to work out-of-the-box with sensible defaults, and can be fully customized for your OpenClaw deployment.

## Agent Name

The main agent's display name is read from your OpenClaw workspace's `IDENTITY.md` file:

```markdown
# IDENTITY.md
- **Name:** YourAgentName
```

- **Auto-detected:** reads from `$OPENCLAW_WORKSPACE/IDENTITY.md` or `$OPENCLAW_DIR/workspace/IDENTITY.md`
- **Default:** `Star` (if no IDENTITY.md is found)
- The name appears in the control bar, agent detail modal, and status messages

## Office Name (Plaque)

The office plaque text is derived from the agent name in `IDENTITY.md`. For an agent named "Luna", the plaque reads **"Luna's Office"**.

You can override `OPENCLAW_WORKSPACE` in your environment to point to a custom workspace directory.

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENCLAW_DIR` | Path to `.openclaw` data directory | `~/.openclaw` (auto-detected) |
| `OPENCLAW_WORKSPACE` | Path to workspace with IDENTITY.md | `$OPENCLAW_DIR/workspace` |
| `STAR_OFFICE_ENV` | Set to `production` for hardening | `development` |
| `FLASK_SECRET_KEY` | Session secret (required in production) | dev default |
| `ASSET_DRAWER_PASS` | Passcode for asset editor | `1234` |
| `STAR_BACKEND_PORT` | Backend listening port | `19000` |

## Travel Mode

To show travel/vacation status messages in the agent's speech bubble:

1. Create a JSON file in `$OPENCLAW_DIR/workspace/config/` named `travel-mode.json` (or `*-trip-mode.json` / `*-travel-mode.json`):

```json
{
  "active": true,
  "statusMessages": [
    "🏖️ Working from the beach",
    "🌴 Remote mode: tropical edition",
    "🌅 Sun, sand, and servers"
  ]
}
```

2. Set `"active": false` to disable, or delete the file.

The `statusMessages` array provides the speech bubble pool — a random message is picked each time. If omitted, generic travel defaults are used.

## Rate Limits

Configure token budget tracking in `rate_limits_config.json` (see `rate_limits_config.sample.json`):

```json
{
  "anthropic": {
    "sessionWindowHours": 5,
    "fiveHourTokenLimit": 300000,
    "weeklyTokenLimit": 5000000,
    "tier": "tier-2",
    "label": "Anthropic (Claude)"
  },
  "openai": {
    "sessionWindowHours": 5,
    "fiveHourTokenLimit": 500000,
    "weeklyTokenLimit": 10000000,
    "tier": "plus",
    "label": "OpenAI (Codex)"
  }
}
```

## Usage Budget

Configure monthly cost tracking in `usage_config.json` (see `usage_config.sample.json`):

```json
{
  "monthlyBudget": 200,
  "warningThreshold": 0.8,
  "pricing": {
    "claude-opus-4-6": {"inputPer1M": 15, "outputPer1M": 75, "cacheReadPer1M": 1.5},
    "default": {"inputPer1M": 3, "outputPer1M": 15, "cacheReadPer1M": 0.3}
  }
}
```

## Guest Agents (Join Keys)

Configure join keys in `join-keys.json` (see `join-keys.sample.json`) to allow other OpenClaw agents to appear in your office:

```json
{
  "keys": [
    {
      "key": "your-secret-key-here",
      "label": "Demo key",
      "maxConcurrent": 3,
      "expiresAt": "2026-12-31T23:59:59"
    }
  ]
}
```

Share the key with other agents — they'll appear as guest sprites in your office.

## Custom Office Background

Use the built-in asset editor (🪚 Decorate button) or the `/openclaw/redecorate` API endpoint to generate AI-powered backgrounds. Requires a Gemini API key configured via the UI or `runtime-config.json`.

## File Reference

| File | Purpose | Tracked in Git? |
|------|---------|-----------------|
| `state.json` | Current agent state | No (`.gitignore`) |
| `agents-state.json` | Multi-agent registry | No |
| `runtime-config.json` | API keys, model config | No |
| `join-keys.json` | Guest agent keys | No |
| `dismissed_agents.json` | Dismissed agent list | No |
| `asset-positions.json` | Custom asset positions | No |
| `rate_limits_config.json` | Token limit thresholds | No |
| `usage_config.json` | Cost budget config | No |
| `*.sample.json` | Example configs | Yes ✓ |
