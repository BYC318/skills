---
name: kothar-mcp-update
description: Update or reinstall the Kothar MCP / Codex tools when the user asks to update Kothar, refresh the MCP client, reinstall Kothar tools, or respond to a Kothar update notice. Do not use for ordinary Figma design-to-code work.
---

# Kothar MCP Update

Use this skill only for Kothar MCP client installation, update, reinstall, or update-status checks. It is separate from `kothar-figma-to-code`: that skill helps with UI implementation, while this one keeps the local Kothar MCP package current.

## Safety

- Do not silently update. Run the installer only when the user asks to update/reinstall/fix Kothar MCP, or when the user explicitly agrees after seeing an update notice.
- Do not edit project files, commit, push, deploy, or restart production services for this workflow.
- Do not print, log, commit, or reveal Kothar account passwords, Figma tokens, queue tokens, or other credentials.
- Prefer the public Kothar installer over ad hoc git/npm steps; it preserves existing local config and updates the bundled MCP code plus Codex skills.

## Update

Detect the local OS and run the matching public installer:

```bash
curl -fsSL https://f2c.quhong.net/mcp/install-kothar.sh | bash
```

```powershell
irm https://f2c.quhong.net/mcp/install-kothar.ps1 | iex
```

If the installer asks how to handle an existing install and the user did not request credential changes, choose the default "only update" path. Change Kothar username/password/Figma token only when the user explicitly asks.

After a successful update, tell the user to restart Codex or open a new Codex session. Codex loads MCP server definitions and skills at session start, so the current session may still use the old tool schema until restart.

## Check Only

When the user asks only to check whether an update is available, prefer:

```bash
node ~/.codex/kothar-tools/scripts/check-update.mjs
```

On Windows, run the equivalent script under `%USERPROFILE%\.codex\kothar-tools\scripts\check-update.mjs` with Node.js. If the script is missing, say the local Kothar package is too old to self-check and use the public installer to update.
