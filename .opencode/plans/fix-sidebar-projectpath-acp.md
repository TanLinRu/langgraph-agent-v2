# Fix Sidebar Collapse, Project Path Guard, ACP Detection

## Issue 1: Sidebar collapse — no way to expand

### Problem
When `sidebarOpen = false`, the `<aside>` gets `width: 0; opacity: 0; pointer-events: none`. The toggle button is **inside** the sidebar, so it's hidden and unclickable — no way to expand.

### Fix: App.vue
Add a floating "reveal" button at the left edge of `.center-col`, visible **only** when sidebar is collapsed.

**Changes to `ui/src/App.vue`:**

1. In `<template>`, after `<Sidebar>` and inside `<div class="center-col">`, add:
```html
<!-- Floating sidebar toggle when collapsed -->
<button v-if="!sidebarOpen" class="sidebar-reveal-btn"
        @click="sidebarOpen = true" title="Expand sidebar">
  <svg ...><polyline points="9 18 15 12 9 6"/></svg>
  <span class="sidebar-reveal-label">Sessions</span>
</button>
```

2. In `<style>`, add CSS:
```css
.sidebar-reveal-btn {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  z-index: 100; width: 28px; height: 64px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px;
  background: var(--bg-glass); border: 1px solid var(--border);
  border-left: none; border-radius: 0 8px 8px 0;
  color: var(--text-muted); cursor: pointer;
  transition: all 0.2s;
}
.sidebar-reveal-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.sidebar-reveal-btn svg { transition: transform 0.2s; }
.sidebar-reveal-btn:hover svg { transform: translateX(2px); }
.sidebar-reveal-label { writing-mode: vertical-rl; font-size: 10px; letter-spacing: 1px; }
```
- `.center-col` needs `position: relative` for absolute positioning to work.

Also, the **sidebar toggle button** inside Sidebar.vue should be kept (it still works when sidebar IS open).

---

## Issue 2: Project path must be configured before sending messages

### Problem
There's no way for the user to set a project path, and no guard prevents sending messages without one. The path is read-only from ACP config.

### Fix: Backend (`server.py` + `checkpoint.py`)
1. **Add `project_path` field to session creation/data.**
   - In `checkpoint.py`: add `project_path` column (optional TEXT, nullable).
   - In `server.py` `POST /api/sessions`: accept optional `project_path` body param.
   - In `server.py` `GET /api/sessions`: return `project_path` in session info.

2. **Add `PATCH /api/sessions/{id}/project-path` endpoint** to update the project path for an existing session.

### Fix: Frontend

1. **`ui/src/stores/sessions.ts`**: Add `projectPath` ref + `setProjectPath()` action that calls the new PATCH endpoint.

2. **`ui/src/components/ChatTab.vue`**:
   - Add a `projectPathConfigured` computed that checks if current session has a `project_path`.
   - When NOT configured, show a **project path prompt overlay** at the top of the chat area (below ChatHeader, above messages):
     ```
     ┌─────────────────────────────┐
     │  📁 请设置项目路径          │
     │  [__________________] [设置]│
     └─────────────────────────────┘
     ```
   - When configured, show the path as a small tag/badge instead.

3. **`ui/src/stores/chat.ts`** — `send()` function:
   - Check `sessionsStore.currentSession?.project_path` — if empty/undefined, show system message `"⚠ 请先设置项目路径"` and return without sending.

4. **`ui/src/components/ChatHeader.vue`** — Replace the current read-only project path with a clickable path that opens the FileExplorer (or keep as-is but pull from session data).

---

## Issue 3: ACP agent detection (opencode on Windows)

### Problem
- `opencode` exists as `opencode.ps1` (PowerShell script). `shutil.which('opencode')` on Windows only checks `PATHEXT` extensions (`.exe`, `.cmd`, `.bat`), NOT `.ps1`.
- `claude-agent-acp` simply not installed — this is accurate.

### Fix: `server.py`

Replace the simple `shutil.which()` in the agents list endpoint and `/api/acp/check/{agent_id}` endpoint with a smarter check:

```python
import sys
import subprocess
import shutil

def _command_available(cmd: str) -> bool:
    if shutil.which(cmd):
        return True
    # Windows: PowerShell scripts (.ps1) aren't found by shutil.which
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Command '{cmd}' -ErrorAction SilentlyStop"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return False
```

Update all ACP availability checks in `server.py` to use `_command_available()` instead of `shutil.which()`.

---

## Implementation Order
1. Issue 1 (sidebar) — smallest, standalone
2. Issue 3 (ACP detection) — small, standalone
3. Issue 2 (project path guard) — largest, depends on understanding the full flow

## Files Changed
| File | Changes |
|------|---------|
| `ui/src/App.vue` | Add floating sidebar reveal button + CSS |
| `server.py` | Add `_command_available()` helper, update ACP checks; add project_path to sessions |
| `src/agent/checkpoint.py` | Add `project_path` column handling |
| `ui/src/stores/sessions.ts` | Add `projectPath` state + `setProjectPath()` |
| `ui/src/stores/chat.ts` | Guard `send()` with project path check |
| `ui/src/components/ChatTab.vue` | Add project path prompt overlay |
| `ui/src/components/ChatHeader.vue` | Update path display (optional) |
| `ui/src/utils/api.ts` | Add `setSessionProjectPath()` API function |
