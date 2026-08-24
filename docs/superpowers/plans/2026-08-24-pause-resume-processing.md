# Pause and Resume Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement pause and resume capabilities for the image processing session across the backend pipeline engine, REST API, and React WebUI, allowing configuration changes during pause and continuing remaining workload on resume.

**Architecture:** A thread-synchronization `threading.Event` inside `ProcessingState` blocks worker threads during pause while keeping in-memory state intact. On resume, `PipelineEngine` dynamically reloads `config.yaml`, updates tag definitions, tag hashes, and AI model parameters, and unblocks workers. The React WebUI provides a unified Start/Pause/Resume toggle button alongside a Stop button, locks the target folder and root directory during active/paused sessions, and displays real-time status.

**Tech Stack:** Python 3.12, FastAPI, pytest, TypeScript, React 18, Tailwind CSS, Lucide React, Vite.

## Global Constraints
- Target folder on Processing tab and Root Directory on Config tab must be disabled while running or paused.
- Pause must allow in-flight AI requests to finish safely before workers suspend.
- Stop when paused must immediately unblock workers and finalize the run summary.
- Resuming must hot-reload `config.yaml` and apply any new or edited tag definitions/models to the remaining candidate images.

---

### Task 1: `ProcessingState` Pause/Resume State and Synchronization

**Files:**
- Modify: `src/exif_tagger/main.py:150-248`
- Test: `tests/test_pipeline_engine.py`

**Interfaces:**
- Consumes: Standard Python `threading.Event`, `threading.RLock`.
- Produces:
  - `ProcessingState.paused: bool` property
  - `ProcessingState.set_paused() -> None`
  - `ProcessingState.set_resumed() -> None`
  - `ProcessingState.wait_if_paused() -> None`
  - `ProcessingState.get_status()` includes `"paused": bool`

- [ ] **Step 1: Write the failing tests for `ProcessingState` pause/resume methods**

Add tests to `tests/test_pipeline_engine.py`:
```python
def test_processing_state_pause_and_resume():
    state = ProcessingState()
    assert state.paused is False
    assert state.running is False

    state.start(10)
    assert state.running is True
    assert state.paused is False

    state.set_paused()
    assert state.paused is True
    assert state.running is True
    status = state.get_status()
    assert status["paused"] is True
    assert any("paused" in log["text"].lower() for log in status["logs"])

    state.set_resumed()
    assert state.paused is False
    assert state.running is True
    status = state.get_status()
    assert status["paused"] is False
    assert any("resumed" in log["text"].lower() for log in status["logs"])


def test_processing_state_finish_clears_pause():
    state = ProcessingState()
    state.start(5)
    state.set_paused()
    assert state.paused is True

    state.finish({"total_processed": 0})
    assert state.paused is False
    assert state.running is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_engine.py -k "test_processing_state_pause_and_resume" -v`
Expected: FAIL with `AttributeError: 'ProcessingState' object has no attribute 'paused'`

- [ ] **Step 3: Implement `ProcessingState` methods in `src/exif_tagger/main.py`**

In `src/exif_tagger/main.py`:
```python
class ProcessingState:
    """Thread-safe state tracker for a running processing session."""

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._processed = 0
        self._total = 0
        self._current_image: str | None = None
        self._stop_requested = False
        self._log_entries: list[dict[str, Any]] = []
        self._log_counter = 0
        self._summary: dict | None = None

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self) -> None:
        with self._lock:
            if self._running and not self._paused:
                self._paused = True
                self._pause_event.clear()
                self.add_log("Processing session paused.", "info")

    def set_resumed(self) -> None:
        with self._lock:
            if self._paused:
                self._paused = False
                self._pause_event.set()
                self.add_log("Processing session resumed.", "info")

    def wait_if_paused(self) -> None:
        while True:
            with self._lock:
                if not self._paused or self._stop_requested:
                    return
            self._pause_event.wait(timeout=0.2)

    def start(self, total_images: int) -> None:
        with self._lock:
            self._running = True
            self._paused = False
            self._pause_event.set()
            self._processed = 0
            self._total = total_images
            self._current_image = None
            self._stop_requested = False
            self._log_entries = []
            self._log_counter = 0
            self._summary = None

    def set_stop_requested(self) -> None:
        with self._lock:
            self._stop_requested = True
            self._paused = False
            self._pause_event.set()

    def finish(self, summary: dict) -> None:
        with self._lock:
            self._running = False
            self._paused = False
            self._pause_event.set()
            self._current_image = None
            self._summary = summary
```
And in `PipelineEngine.get_status()` / `ProcessingState.get_status()`:
```python
    def get_status(self) -> dict:
        """Get current processing state."""
        s = self.state
        return {
            "running": s.running,
            "paused": s.paused,
            "processed": s.processed,
            "total": s.total,
            "currentImage": s.current_image,
            "progressPct": s.progress_pct,
            "stopRequested": s.stop_requested,
            "logs": s.get_logs(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_engine.py -k "test_processing_state_pause" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/main.py tests/test_pipeline_engine.py
git commit -m "feat(pipeline): add pause/resume state and synchronization event"
```

---

### Task 2: `PipelineEngine` Pause, Resume, Stop & Dynamic Config Reloading

**Files:**
- Modify: `src/exif_tagger/main.py:250-630`
- Test: `tests/test_pipeline_engine.py`

**Interfaces:**
- Consumes: `ProcessingState`, `exif_tagger.config.load_config`, `exif_tagger.config.compute_tag_hash`, `exif_tagger.db.evaluate_thresholds_locally`.
- Produces:
  - `PipelineEngine.pause() -> dict`
  - `PipelineEngine.resume() -> dict`
  - Dynamic reload of `self._config`, `tag_hashes` inside `process_image` and `resume`.

- [ ] **Step 1: Write integration tests for `PipelineEngine.pause()`, `PipelineEngine.resume()`, and hot config reload**

Add test to `tests/test_pipeline_engine.py`:
```python
def test_pipeline_engine_pause_resume_hot_reload(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import yaml
    from exif_tagger.models.schema import TagDefinition

    cfg_file = tmp_path / "config.yaml"
    initial_cfg = {
        "root_directory": str(tmp_path),
        "ai_model": {
            "base_url": "https://api.openai.com/v1",
            "model_name": "model-v1",
            "api_key": "test",
        },
        "tags": {
            "tag1": {"description": "Initial tag 1", "threshold": 0.7}
        }
    }
    cfg_file.write_text(yaml.safe_dump(initial_cfg))

    engine = PipelineEngine(config_path=str(cfg_file))
    engine.state.start(5)

    # Pause
    res = engine.pause()
    assert res["status"] == "paused"
    assert engine.state.paused is True

    # Modify config on disk while paused
    updated_cfg = {
        "root_directory": str(tmp_path),
        "ai_model": {
            "base_url": "https://api.openai.com/v1",
            "model_name": "model-v2",
            "api_key": "test",
        },
        "tags": {
            "tag1": {"description": "Updated tag 1", "threshold": 0.8},
            "tag2": {"description": "New tag 2", "threshold": 0.75}
        }
    }
    cfg_file.write_text(yaml.safe_dump(updated_cfg))

    # Resume
    res_resume = engine.resume()
    assert res_resume["status"] == "resumed"
    assert engine.state.paused is False
    assert engine._config.ai_model.model_name == "model-v2"
    assert "tag2" in engine._config.tags
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_engine.py -k "test_pipeline_engine_pause_resume_hot_reload" -v`
Expected: FAIL with `AttributeError: 'PipelineEngine' object has no attribute 'pause'`

- [ ] **Step 3: Implement `pause()`, `resume()`, and hot config reload in `PipelineEngine`**

In `src/exif_tagger/main.py`:
- In `start_session`:
  - Store shared mutable context (e.g. `self._live_config = config`, `self._live_tag_hashes = tag_hashes`) accessible by `process_image`.
  - In `process_image(img_path)`:
    - At start of function: `self.state.wait_if_paused()`
    - If `self.state.stop_requested`: return
    - Read `current_config = self._config` and `current_tag_hashes = self._live_tag_hashes`.
    - Build `target_tags` using `current_config.tags`.
    - Use `current_config.ai_model`, `current_config.max_image_dimension`, `current_config.guardrails`.
- Implement `pause()`:
```python
    def pause(self) -> dict:
        """Pause current processing session."""
        self.state.set_paused()
        return {
            "status": "paused",
            "processed": self.state.processed,
        }
```
- Implement `resume()`:
```python
    def resume(self) -> dict:
        """Resume current processing session with reloaded configuration."""
        from exif_tagger.config import compute_tag_hash
        from exif_tagger.db import evaluate_thresholds_locally

        config = self._load_config()
        self._live_tag_hashes = {
            name: compute_tag_hash(tag_def.description) for name, tag_def in config.tags.items()
        }

        # Zero-cost local threshold re-evaluation with updated tags/thresholds
        try:
            evaluate_thresholds_locally(
                root_directory=config.root_directory,
                active_tags=config.tags,
                tag_hashes=self._live_tag_hashes,
            )
        except Exception as e:
            logging.getLogger("exif_tagger").warning("Local threshold re-evaluation failed on resume: %s", e)

        self.state.set_resumed()
        return {
            "status": "resumed",
            "processed": self.state.processed,
        }
```
- In `stop()`:
```python
    def stop(self) -> dict:
        """Request graceful stop of current session."""
        self.state.set_stop_requested()
        time.sleep(0.5)  # Give thread a moment to notice
        summary = self.state.summary or {}
        return {
            "status": "stopped",
            "processed": self.state.processed,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_engine.py -k "test_pipeline_engine_pause_resume_hot_reload" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/main.py tests/test_pipeline_engine.py
git commit -m "feat(pipeline): implement engine pause and resume with dynamic config reloading"
```

---

### Task 3: Backend REST Endpoints (`/api/pause`, `/api/resume`, `/api/status`, `/api/stop`)

**Files:**
- Modify: `src/exif_tagger/server.py:237-286`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `PipelineEngine.pause()`, `PipelineEngine.resume()`, `PipelineEngine.stop()`, `PipelineEngine.get_status()`.
- Produces:
  - `POST /api/pause` -> `{"status": "paused"}` (or 400 if not running or already paused)
  - `POST /api/resume` -> `{"status": "resumed"}` (or 400 if not running or not paused)
  - `GET /api/status` includes `paused: bool`
  - `POST /api/stop` works when paused

- [ ] **Step 1: Write tests for `/api/pause` and `/api/resume` endpoints**

In `tests/test_server.py`:
```python
class TestApiPauseResume:
    def test_pause_no_running_session(self, client):
        resp = client.post("/api/pause")
        assert resp.status_code == 400
        assert "No active processing session" in resp.json()["detail"]

    def test_resume_no_running_session(self, client):
        resp = client.post("/api/resume")
        assert resp.status_code == 400
        assert "No active processing session" in resp.json()["detail"]

    def test_pause_and_resume_flow(self, client, monkeypatch):
        from exif_tagger import server

        engine = server._get_engine()
        engine.state.start(10)

        # First pause succeeds
        resp = client.post("/api/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # Status shows paused
        s_resp = client.get("/api/status")
        assert s_resp.status_code == 200
        assert s_resp.json()["paused"] is True
        assert s_resp.json()["running"] is True

        # Second pause fails
        resp2 = client.post("/api/pause")
        assert resp2.status_code == 400

        # Resume succeeds
        resp_resume = client.post("/api/resume")
        assert resp_resume.status_code == 200
        assert resp_resume.json()["status"] == "resumed"

        # Status shows not paused
        s_resp2 = client.get("/api/status")
        assert s_resp2.json()["paused"] is False

        # Stop while running or paused works
        resp_stop = client.post("/api/stop")
        assert resp_stop.status_code == 200
        assert resp_stop.json()["status"] == "stopped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -k "TestApiPauseResume" -v`
Expected: FAIL with 404 Not Found for `/api/pause`

- [ ] **Step 3: Implement the endpoints in `src/exif_tagger/server.py`**

In `src/exif_tagger/server.py`:
```python
@app.post("/api/pause")
def api_pause():
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No active processing session is running")
    if engine.state.paused:
        raise HTTPException(status_code=400, detail="Processing session is already paused")

    result = engine.pause()
    return result


@app.post("/api/resume")
def api_resume():
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No active processing session is running")
    if not engine.state.paused:
        raise HTTPException(status_code=400, detail="Processing session is not paused")

    result = engine.resume()
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -k "TestApiPauseResume" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/exif_tagger/server.py tests/test_server.py
git commit -m "feat(api): add /api/pause and /api/resume endpoints"
```

---

### Task 4: Frontend Types and `useProcessing` Hook Updates

**Files:**
- Modify: `webui/src/types/index.ts`
- Modify: `webui/src/hooks/useProcessing.ts`

**Interfaces:**
- Consumes: `/api/status`, `/api/pause`, `/api/resume`, `/api/stop`.
- Produces:
  - `ProcessingStatus.paused?: boolean`
  - `useProcessing().isPaused: boolean`
  - `useProcessing().pauseProcessing: () => Promise<{ success: boolean; error?: string }>`
  - `useProcessing().resumeProcessing: () => Promise<{ success: boolean; error?: string }>`

- [ ] **Step 1: Update `webui/src/types/index.ts`**

Add `paused?: boolean;` to `ProcessingStatus` interface:
```typescript
export interface ProcessingStatus {
  running: boolean;
  paused?: boolean;
  processed: number;
  total: number;
  currentImage: string | null;
  progressPct: number;
  stopRequested: boolean;
  logs: BackendLogItem[];
  summary?: ProcessingSummary | null;
}
```

- [ ] **Step 2: Update `webui/src/hooks/useProcessing.ts`**

In `webui/src/hooks/useProcessing.ts`:
- Add `isPaused` state:
```typescript
const [isPaused, setIsPaused] = useState<boolean>(false);
```
- In `fetchStatus`:
```typescript
const runningState = Boolean(data.running);
const pausedState = Boolean(data.paused);
const prevWasRunning = wasRunningRef.current;
wasRunningRef.current = runningState;

if (runningState) {
  setIsRunning(true);
  setIsPaused(pausedState);
  setStatusText(pausedState ? 'Paused' : 'Running');
  setSummary(data.summary || null);
  setProcessedCount(data.processed || 0);
  setTotalCount(data.total || 0);
  setProgressPct(data.progressPct || 0);
} else if (data.stopRequested) {
  setIsRunning(false);
  setIsPaused(false);
  setStatusText('Stopping...');
} else {
  setIsRunning(false);
  setIsPaused(false);
  ...
```
- Add `pauseProcessing` and `resumeProcessing`:
```typescript
const pauseProcessing = useCallback(async () => {
  try {
    const resp = await fetch('/api/pause', { method: 'POST' });
    if (resp.ok) {
      setIsPaused(true);
      setStatusText('Paused');
      return { success: true };
    } else {
      const errData = await resp.json();
      return { success: false, error: errData.detail || 'Failed to pause session' };
    }
  } catch (e: any) {
    return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
  }
}, []);

const resumeProcessing = useCallback(async () => {
  try {
    const resp = await fetch('/api/resume', { method: 'POST' });
    if (resp.ok) {
      setIsPaused(false);
      setStatusText('Running');
      return { success: true };
    } else {
      const errData = await resp.json();
      return { success: false, error: errData.detail || 'Failed to resume session' };
    }
  } catch (e: any) {
    return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
  }
}, []);
```
- Return `isPaused`, `pauseProcessing`, `resumeProcessing` from `useProcessing`.

- [ ] **Step 3: Run TypeScript compiler check**

Run: `npm run build` in `webui/`
Expected: Build passes without type errors.

- [ ] **Step 4: Commit**

```bash
git add webui/src/types/index.ts webui/src/hooks/useProcessing.ts
git commit -m "feat(webui): add isPaused state and pause/resume handlers in useProcessing"
```

---

### Task 5: Frontend UI Components (`SessionCard`, `ProgressCard`, `ProcessingTab`, `ConfigTab`)

**Files:**
- Modify: `webui/src/components/processing/SessionCard.tsx`
- Modify: `webui/src/components/processing/ProgressCard.tsx`
- Modify: `webui/src/components/processing/ProcessingTab.tsx`
- Modify: `webui/src/components/config/ConfigTab.tsx`

**Interfaces:**
- Consumes: `isPaused`, `pauseProcessing`, `resumeProcessing` from `useProcessing`.
- Produces:
  - Dynamic Start/Pause/Resume primary button with corresponding icons and states.
  - Active Stop button when running or paused.
  - Disabled `folderPath` input and Browse button when `isRunning`.
  - Disabled `root_directory` input on `ConfigTab` when `isRunning`.
  - Paused badge styling on `ProgressCard`.

- [ ] **Step 1: Update `SessionCard.tsx`**

Update `SessionCardProps`:
```typescript
export interface SessionCardProps {
  rootDirectory?: string;
  folderPath: string;
  onFolderPathChange: (path: string) => void;
  onBrowseFolders: () => void;
  maxImages: number | null;
  onMaxImagesChange: (max: number | null) => void;
  isRunning: boolean;
  isPaused: boolean;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}
```
Update primary button handling:
```tsx
const handlePrimaryAction = () => {
  if (!isRunning) {
    onStart();
  } else if (isPaused) {
    onResume();
  } else {
    onPause();
  }
};
```
Render primary and stop buttons:
```tsx
<div className="flex items-center gap-3 pt-2">
  {!isRunning ? (
    <Button
      type="submit"
      variant="default"
      className="flex items-center gap-2"
    >
      <Play className="w-4 h-4" />
      Start Processing
    </Button>
  ) : isPaused ? (
    <Button
      type="button"
      variant="default"
      onClick={onResume}
      className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
    >
      <Play className="w-4 h-4" />
      Resume Processing
    </Button>
  ) : (
    <Button
      type="button"
      variant="secondary"
      onClick={onPause}
      className="flex items-center gap-2 border border-amber-500/40 text-amber-500 hover:bg-amber-500/10"
    >
      <Pause className="w-4 h-4" />
      Pause Processing
    </Button>
  )}

  <Button
    type="button"
    variant="destructive"
    disabled={!isRunning}
    onClick={onStop}
    className="flex items-center gap-2"
  >
    <Square className="w-4 h-4" />
    Stop Processing
  </Button>
</div>
```

- [ ] **Step 2: Update `ProgressCard.tsx`**

Add `isPaused?: boolean` prop.
Update badge rendering:
```tsx
<Badge
  variant="outline"
  className={`px-2.5 py-0.5 text-xs font-medium ${
    isRunning && !isPaused
      ? 'bg-amber-500/10 text-amber-500 border-amber-500/30'
      : isPaused
      ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
      : statusText === 'Completed'
      ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30'
      : statusText === 'Completed with errors'
      ? 'bg-rose-500/10 text-rose-500 border-rose-500/30'
      : 'bg-slate-500/10 text-slate-400 border-slate-500/30'
  }`}
>
  {isRunning && !isPaused && <Loader2 className="w-3 h-3 mr-1 inline animate-spin" />}
  {isPaused && <Pause className="w-3 h-3 mr-1 inline" />}
  {statusText}
</Badge>
```

- [ ] **Step 3: Wire up handlers in `ProcessingTab.tsx`**

Pass `isPaused`, `pauseProcessing`, `resumeProcessing` to `SessionCard` and `ProgressCard`:
```tsx
const handlePause = async () => {
  const res = await pauseProcessing();
  if (res.success) {
    showToast('Processing session paused', 'info');
  } else if (res.error) {
    showToast(res.error, 'error');
  }
};

const handleResume = async () => {
  const res = await resumeProcessing();
  if (res.success) {
    showToast('Processing session resumed', 'success');
  } else if (res.error) {
    showToast(res.error, 'error');
  }
};
```

- [ ] **Step 4: Lock `root_directory` in `ConfigTab.tsx` when session is running or paused**

In `ConfigTab.tsx`, fetch `/api/status` or check status to disable `root_directory`:
```tsx
<div className="space-y-1.5">
  <label className="text-sm font-medium text-foreground">Root Directory Path</label>
  <Input
    value={formData.root_directory || ''}
    onChange={(e) =>
      setFormData((prev) => ({ ...prev, root_directory: e.target.value }))
    }
    placeholder="/data/images"
    disabled={isSessionActive}
    className="font-mono text-sm"
  />
  <p className="text-xs text-muted-foreground">
    {isSessionActive
      ? 'Root directory is locked while a processing session is active or paused.'
      : 'Base path on server disk containing target image subfolders.'}
  </p>
</div>
```

- [ ] **Step 5: Build webui and verify bundle**

Run: `npm run build` in `webui/`
Expected: Build passes with 0 errors.

- [ ] **Step 6: Commit**

```bash
git add webui/src/components/
git commit -m "feat(webui): add pause/resume button UI, paused badge, and directory locking"
```

---

### Task 6: Full Verification and E2E Smoke Tests

**Files:**
- Modify/Add: `tests/e2e/test_ui_tabs.py` or new pause/resume UI test
- Run: Full test suite (`pytest`)

- [ ] **Step 1: Add E2E / UI tests for Pause/Resume button states**

In `tests/e2e/test_ui_tabs.py`:
```python
def test_processing_action_buttons_present(page):
    page.goto("http://localhost:8000")
    start_btn = page.locator("button:has-text('Start Processing')")
    assert start_btn.is_visible()
    stop_btn = page.locator("button:has-text('Stop Processing')")
    assert stop_btn.is_visible()
    assert stop_btn.is_disabled()
```

- [ ] **Step 2: Run all backend and e2e tests**

Run: `pytest`
Expected: All tests pass (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: add tests for pause/resume processing workflow"
```
