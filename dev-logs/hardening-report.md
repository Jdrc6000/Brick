# Brick — Full Hardening Report

Every bug found, classified by severity, with the fix location.

---

## CRITICAL

### BUG-28 — SyntaxError in server.py on Python ≤ 3.11
**File:** `server.py`  
**Lines:** `get_agent()`, `reset()`, `chat_stream()`  
**Problem:** `f"device-{device["name"]}"` — nested same-quote f-strings are a `SyntaxError`
in Python 3.11 and earlier. Would crash the entire server at import time on older runtimes.  
**Fix:** Extracted to `_session_id_for(device)` helper that builds the key without nesting.

---

### BUG-2 / BUG-3 — Unbound `msg` or wrong final text after max_iterations
**File:** `agent/runner.py`  
**Problem:** After exhausting `max_iterations` without a clean text response, the runner
returned whatever the last tool-call message dict was. `msg.get("content")` on a tool-call
message is empty or None, so the user got a blank or error response. In `stream()`, the
fallback iterated char-by-char over an empty string and never guaranteed `done` was emitted.  
**Fix:** Explicit fallback string returned and yielded. `done` is now guaranteed exactly once.

---

### BUG-4 — `done` SSE event never emitted in some stream paths
**File:** `agent/runner.py` → `stream()`  
**Problem:** If Ollama raised an exception during the initial chat call (before any tool calls),
the generator returned without ever yielding `done`. SSE consumers would hang indefinitely.  
**Fix:** All exception paths now `yield {"type": "done", ...}` before `return`.

---

### BUG-31 — Duplicate `done` SSE event
**File:** `server.py` → `chat_stream()`  
**Problem:** The `generate()` finally clause unconditionally emitted `done`, but `agent.stream()`
already emits `done` on its clean exit path. Every normal response sent two `done` events.
JS consumers that called `finalise()` twice would re-render the message, potentially blanking it.  
**Fix:** `generate()` tracks `done_sent`; finally only emits if the agent generator didn't.
The agent generator also now always emits exactly one `done`.

---

## HIGH

### BUG-7 — JSON parse before HTTP OK check in RemoteToolExecutor
**File:** `tools/remote_executor.py`  
**Problem:** `response.json()` was called before `response.ok` was checked. A non-JSON
response body (nginx 502, HTML error page, load balancer timeout) would raise `ValueError`
which was caught by the outer bare `except Exception`, returning a raw Python exception
string to the model instead of a clean error.  
**Fix:** Check `response.ok` first. Parse JSON. If parse fails, return a structured error
with an excerpt of the raw body for debugging.

### BUG-8 — HTTP timeout too short for sandbox_exec
**File:** `tools/remote_executor.py`  
**Problem:** All remote tool calls used `REQUEST_TIMEOUT = 30`. `sandbox_exec` supports
up to 120 s execution. Commands running >30 s would be cut off by the HTTP layer while
still running in the sandbox — leaving orphaned processes and confusing output.  
**Fix:** Per-tool timeout table. `sandbox_exec` and `sandbox_install_package` use 130 s.

### BUG-13 — BusyBox `find` doesn't support `-printf`
**File:** `tools/builtins/sandbox.py` → `SandboxListFiles`  
**Problem:** The Alpine Linux container uses BusyBox, which does not implement GNU
`find`'s `-printf`. The recursive listing silently failed with an error, returning nothing.  
**Fix:** Use `find ... -ls` for recursive (BusyBox-compatible) and `ls -lah` for flat.

### BUG-18 — Per-core CPU percentages always near 0%
**File:** `tools/builtins/system_metrics.py` → `GetCpuUsage`  
**Problem:** `psutil.cpu_percent(interval=1.0)` was called (blocking), then immediately
`psutil.cpu_percent(percpu=True, interval=None)` was called. The second call returns
usage accumulated since the *previous* call — which was microseconds ago — so all cores
showed ~0%. The dashboard displayed a flat CPU graph even under load.  
**Fix:** Single blocking call: `psutil.cpu_percent(interval=interval, percpu=True)`.
Overall is computed as the mean of per-core values.

### BUG-23 — `find -printf` not available on macOS (brick-client on Mac)
**File:** `tools/builtins/files_and_logs.py` → `FindLargeFiles`  
**Problem:** GNU `find`'s `-printf` is not available on macOS (BSD find). `brick-client.py`
running on Josh's or Will's Mac would get an error on every `find_large_files` call.  
**Fix:** Use portable `find -type f -size +NM` then `os.stat()` each result in Python.

---

## MEDIUM

### BUG-1 — `MAX_ITERATIONS = 0` causes unbound variable crash
**File:** `agent/runner.py`, `config.py`  
**Problem:** If `max_iterations` were set to 0 (or 1 and the model immediately used a tool),
the `for` loop would never execute, leaving `msg` unbound on the fallback return path.  
**Fix:** `config.py` asserts `MAX_ITERATIONS > 0`. Runner clamps to `max(1, ...)`.

### BUG-5 — Empty string appended to history on iteration exhaustion
**File:** `agent/runner.py`  
**Problem:** After max iterations, `final` was `(msg.get("content") or "").strip()` where
`msg` was a tool-call message — content is empty. An empty assistant turn was saved to
history and memory, causing the next session resume to inject an empty assistant message
into context which could confuse the model.  
**Fix:** Fallback string is always non-empty and informative.

### BUG-12 — chmod failure silently returns success in SandboxWriteFile
**File:** `tools/builtins/sandbox.py`  
**Problem:** `chmod` result was ignored. A file written with wrong permissions (e.g. a
script that should be executable) would report success even if chmod failed.  
**Fix:** chmod result checked; `chmod_warning` field added to response if it fails.

### BUG-15 — pip3 may not exist in Alpine container
**File:** `tools/builtins/sandbox.py` → `SandboxInstallPackage`  
**Problem:** Minimal Alpine images often have `pip` but not `pip3`. The command would fail
with "not found" if only `pip` existed.  
**Fix:** `pip3 install ... || pip install ...` fallback.

### BUG-17 — Packet loss regex fails on float percentages
**File:** `tools/builtins/network.py` → `PingHost`  
**Problem:** Loss regex `(\d+)%` only matched integers. macOS `ping` reports `0.0% packet loss`.
Loss would not be captured, leaving `packet_loss_percent` absent from results.  
**Fix:** `(\d+\.?\d*)%` matches both `0%` and `0.0%`. Stored as `float`.

### BUG-19 — `cpu_percent(interval=0.1)` in `_proc_detail` causes O(n*0.1s) blocking
**File:** `tools/builtins/process_management.py` → `_proc_detail`  
**Problem:** `SearchProcess` called `_proc_detail` per matched process with a 0.1 s blocking
interval. On a system with 200 processes all matching a broad search, this adds 20 seconds
of latency. Under `ListProcesses` this was already avoided (attrs pre-fetched via
`process_iter`), but `SearchProcess` wasn't.  
**Fix:** `_proc_detail` uses `cpu_percent(interval=None)` (non-blocking, returns cached value).

### BUG-24 — `os.scandir` can raise `OSError` (not just subclasses)
**File:** `tools/builtins/files_and_logs.py` → `ListDirectory`  
**Problem:** Only `PermissionError` and `FileNotFoundError` were caught around `os.scandir()`.
On some filesystems (NFS, FUSE, broken symlinks), `OSError` with other errno values can be raised.  
**Fix:** Catch `OSError` at the `scandir()` call; catch `OSError` in the per-entry loop too.

### BUG-32 — `ast.literal_eval` on tool output in server.py
**File:** `server.py` → `tool_exec()`  
**Problem:** After `json.loads` failed, `ast.literal_eval(raw)` was called on arbitrary
tool output. This is unnecessary complexity: `ast.literal_eval` can raise `ValueError`,
`SyntaxError`, or other exceptions on unexpected input, and the coercion is semantically
wrong (a string `"True"` becomes Python `True`).  
**Fix:** Try JSON parse; fall back to raw string. No `ast.literal_eval`.

### BUG-10 — SandboxReset compose file path uses relative `__file__`
**File:** `tools/builtins/sandbox.py`  
**Problem:** `os.path.join(os.path.dirname(__file__), "..", "..", "..", "docker-compose.yml")`
silently produces a wrong path if the interpreter was launched with a relative `sys.argv[0]`
and `__file__` is relative. `os.path.exists()` on it would return `False`, causing recreate
to fail with "docker-compose.yml not found — recreate manually."  
**Fix:** `Path(__file__).resolve()` at import time gives an absolute path unconditionally.

---

## LOW / INFORMATIONAL

### BUG-36 — No fetch() timeout in frontend
**File:** `templates/index.html` JS  
**Problem:** `callTool()` and `callLocalTool()` used bare `fetch()` with no timeout.
If the server was unresponsive, the UI would hang with a spinner indefinitely.  
**Fix:** `AbortController`-based timeout. Default 35 s; 135 s for sandbox tools.
See `TEMPLATE_PATCHES.js`.

### BUG-38 — XSS via marked.parse() without sanitization
**File:** `templates/index.html` JS (and error page templates)  
**Problem:** `body.innerHTML = marked.parse(content)` renders raw HTML from the LLM response.
marked.js does not sanitize by default. A jailbroken or misbehaving model could inject
`<script>` tags or event handlers that execute in the user's browser.  
**Fix:** Wrap all `marked.parse()` calls in `DOMPurify.sanitize()`. Add DOMPurify CDN
script tag to all templates. See `TEMPLATE_PATCHES.js`.

### BUG-29 — `_agents` dict not lock-protected
**File:** `server.py`  
**Problem:** Under concurrent requests, two threads could race on `_agents` dict mutation.  
**Fix:** `threading.Lock()` wraps all `_agents` reads/writes. Noted: run with
`--workers 1` under gunicorn for simplicity, or use this lock for threaded mode.

### BUG-20 — KillProcess does not verify termination
**Severity:** Informational — by design `SIGTERM` is advisory.  
No fix applied; adding a wait/poll would change the tool's async semantics.

### BUG-21/22 — DuckDuckGo scraper fragility
**Severity:** Informational — no stable DDG API available.  
The scraper works until DDG changes their HTML structure. No fix applied.

### BUG-26 — Hardcoded BRICK_SERVER_IP in brick-client.py
**Severity:** Operational / configuration issue, not a code bug.  
Document: update `BRICK_SERVER_IP` in `brick-client.py` when the Pi's IP changes.

---

## Files Changed

| File | Bugs Fixed |
|------|-----------|
| `config.py` | BUG-1 (assert guard) |
| `agent/runner.py` | BUG-1/2/3/4/5 |
| `tools/remote_executor.py` | BUG-7/8 |
| `tools/builtins/sandbox.py` | BUG-10/12/13/15 |
| `tools/builtins/system_metrics.py` | BUG-18 |
| `tools/builtins/network.py` | BUG-17 |
| `tools/builtins/files_and_logs.py` | BUG-23/24 |
| `tools/builtins/process_management.py` | BUG-19 |
| `server.py` | BUG-28/29/31/32 |
| `TEMPLATE_PATCHES.js` | BUG-36/38 (instructions) |