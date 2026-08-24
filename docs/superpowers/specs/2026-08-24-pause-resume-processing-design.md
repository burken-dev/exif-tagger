# Design Specification: Pause and Resume Processing Session

## Overview
This specification details the addition of **Pause** and **Resume** capabilities to the processing workflow in `exif-tagger`. When a session is paused, image processing stops gracefully after the in-flight image completes, the base folder inputs are locked, and progress status is retained. While paused, the user can edit settings in the Configuration tab (AI vision model, prompts, tag definitions, thresholds). Upon resuming, the engine reloads the updated configuration and applies it to the remaining images in the batch.

---

## 1. Backend Architecture

### 1.1 `ProcessingState` Enhancements (`src/exif_tagger/main.py`)
- **State Properties**:
  - `_paused: bool = False`
  - `_pause_event: threading.Event = threading.Event()` (initially set)
- **Methods**:
  - `set_paused()`: sets `_paused = True`, clears `_pause_event`, and logs `"Processing session paused."`.
  - `set_resumed()`: sets `_paused = False`, sets `_pause_event`, and logs `"Processing session resumed."`.
  - `wait_if_paused()`: blocks on `_pause_event.wait()` as long as `_paused` is True and `_stop_requested` is False.
  - `finish()` and `set_stop_requested()`: ensure `_pause_event.set()` is called to guarantee no threads remain blocked if a stop or completion occurs while paused.
- **Status Reporting (`get_status()`)**:
  - Exposes `paused: bool` alongside existing fields (`running`, `processed`, `total`, `currentImage`, `progressPct`, `stopRequested`, `logs`).

### 1.2 `PipelineEngine` Execution Lifecycle (`src/exif_tagger/main.py`)
- **Worker Execution Loop**:
  - Before processing each image (or when worker starts task), calls `self.state.wait_if_paused()`.
  - If `stop_requested` is detected upon waking, the worker exits immediately.
- **Dynamic Config Reload on Resume**:
  - `engine.resume()` re-executes `self._load_config()` from `CONFIG_PATH`.
  - Reloads active tags, AI model parameters (`concurrency`, `base_url`, `model_name`, `max_tokens`, `temperature`, `params`, etc.), guardrail rules, and re-computes `tag_hashes`.
  - Worker processing tasks evaluate remaining images with reference to the live mutable config & tag definitions.
  - Calls `evaluate_thresholds_locally` to update any cached scores if thresholds changed.
  - Calls `self.state.set_resumed()`.
- **Stop While Paused**:
  - `engine.stop()` unblocks any paused workers by setting `_pause_event`, flags `stop_requested`, cancels pending executor tasks, and finalizes the run summary.

---

## 2. API Endpoints (`src/exif_tagger/server.py`)

### 2.1 `POST /api/pause`
- **Pre-conditions**: Session must be running (`engine.state.running == True`) and not already paused (`engine.state.paused == False`). Returns `400 Bad Request` if invalid.
- **Action**: Calls `engine.pause()`.
- **Response**: `{"status": "paused"}`.

### 2.2 `POST /api/resume`
- **Pre-conditions**: Session must be running (`engine.state.running == True`) and currently paused (`engine.state.paused == True`). Returns `400 Bad Request` if invalid.
- **Action**: Calls `engine.resume()`.
- **Response**: `{"status": "resumed"}`.

### 2.3 `POST /api/stop`
- **Behavior**: If session is running (either active or paused), gracefully stops the session, unblocks paused workers, and returns `{"status": "stopped", "processed": ...}`.

### 2.4 `GET /api/status`
- **Response Structure**:
```json
{
  "running": true,
  "paused": true,
  "processed": 14,
  "total": 50,
  "currentImage": null,
  "progressPct": 28.0,
  "stopRequested": false,
  "logs": [...],
  "summary": null
}
```

---

## 3. Frontend Architecture

### 3.1 Hook Updates (`webui/src/hooks/useProcessing.ts`)
- **State**:
  - `isPaused: boolean` (derived from `/api/status`).
  - `statusText`: displays `"Running"` when active, `"Paused"` when paused, `"Stopping..."` when stop is requested, `"Completed"` / `"Completed with errors"` upon finish.
- **Actions**:
  - `pauseProcessing(): Promise<{ success: boolean; error?: string }>`
  - `resumeProcessing(): Promise<{ success: boolean; error?: string }>`
  - `stopProcessing(): Promise<{ success: boolean; error?: string }>`

### 3.2 UI Components

#### `webui/src/components/processing/SessionCard.tsx`
- **Primary Action Button**:
  - **Idle (`!isRunning`)**: `Start Processing` (Play icon, primary styling).
  - **Running (`isRunning && !isPaused`)**: `Pause Processing` (Pause icon, secondary/amber-bordered styling).
  - **Paused (`isRunning && isPaused`)**: `Resume Processing` (Play icon, primary styling).
- **Stop Button**:
  - `Stop Processing` (Square icon, destructive variant).
  - Enabled whenever `isRunning` is True (both when running and when paused).
- **Input Controls**:
  - `folderPath` input and `Browse` button are disabled whenever `isRunning` is True (both running and paused).

#### `webui/src/components/processing/ProgressCard.tsx`
- Badge displays:
  - **Running**: amber badge with spinning loader and `"Running"` label.
  - **Paused**: amber/slate badge with pause icon and `"Paused"` label.
  - **Completed / Idle**: standard completed/idle badges.
- Progress bar and `processedCount / totalCount` remain frozen during pause.

#### `webui/src/components/config/ConfigTab.tsx`
- Checks `isRunning` from session status.
- `root_directory` input is disabled while `isRunning` (running or paused), with tooltip/subtext: `"Root directory cannot be changed while a processing session is active or paused."`.
- All other fields (AI Model settings, prompt templates, guardrails, tag definitions, and thresholds) remain fully editable and saveable during pause.

---

## 4. Testing & Verification

### 4.1 Backend Tests (`tests/test_pipeline_engine.py` & `tests/test_server.py`)
- Unit tests for `ProcessingState` pause / resume state transitions, `_pause_event` synchronization, and thread safety.
- Tests for `PipelineEngine.pause()` and `PipelineEngine.resume()` confirming config reload and worker loop resumption.
- API tests for `POST /api/pause` and `POST /api/resume` verifying valid states, error codes (400 if already paused / not running), and `/api/status` schema.
- Test verifying `POST /api/stop` works cleanly when called on a paused session.

### 4.2 Frontend Build & Integration
- TypeScript compilation and Vite bundle verification (`npm run build`).
- End-to-end and UI component rendering tests for Start / Pause / Resume / Stop button state transitions.
