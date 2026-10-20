# Dashboard Voice Input & Waveform Visualizer — Design

**Date:** 2026-04-10
**Author:** brainstorming session (Claude + user)
**Status:** Approved design, ready for implementation plan
**Target file:** `dashboard/static/index.html`

---

## 1. Overview

Add a voice/mic input feature to the dashboard input row, styled after Telegram's voice message UI. User clicks a microphone button next to the text field, the input row transforms in place to show a live waveform visualizer with Cancel and Stop controls, and the recognized transcript is deposited into the existing text input for review before sending.

**Zero server-side changes.** The feature is implemented entirely in `dashboard/static/index.html` using the browser's built-in Web Speech API (`SpeechRecognition`) and Web Audio API (`AudioContext` + `AnalyserNode`). Once the transcript lands in the input field, the existing `sendCommand()` path carries it to the backend via the already-working WebSocket → `/user_input` ROS topic chain.

**Scope:** 1 file modified, ~250 lines added (HTML + CSS + JS).

## 2. User-Facing Behavior

### 2.1 Decisions (approved)

| # | Question | Answer |
|---|----------|--------|
| Q1 | Auto-send or fill-for-review after transcript? | **B — Fill input field for review.** User clicks Send to confirm. |
| Q2 | Recording stop trigger? | **D — Click to start, auto-stop on silence + visible Cancel button.** Stop button also available. |
| Q3 | Recording UI layout? | **B — Input row transforms in place** (Telegram-style). |
| Q4 | Language support? | **A — English only (`en-US`).** |
| Q5 | Mic-unavailable presentation? | **B — Always show mic button, error toast on failure.** |

### 2.2 User Flow

```
[IDLE]
 ┌──────────────────────────────────────────┐
 │ [🎤]  [______type a command______]  [Send] │
 └──────────────────────────────────────────┘
         ↓ click mic
[RECORDING]
 ┌──────────────────────────────────────────┐
 │ [Cancel]  [●  ~~~~waveform~~~~]  [Stop]  │   ← red tint, live waveform
 └──────────────────────────────────────────┘
         ↓ Stop / auto-stop on silence
[IDLE, transcript filled]
 ┌──────────────────────────────────────────┐
 │ [🎤]  [go to table 3_____________]  [Send] │
 └──────────────────────────────────────────┘
         ↓ click Send (existing path)
```

Cancel / Esc → return to IDLE with **input unchanged** (no transcript deposited).

## 3. Architecture

### 3.1 Approach: inline in `index.html` only

**Reasoning:** the existing `sendCommand()` already handles the text-to-ROS path via WebSocket. Voice is just a second way to fill the input field. No Python, no WebSocket schema additions, no new endpoints.

```
┌──────────────────────────────────────────────────────────┐
│ Browser: dashboard/static/index.html                      │
│                                                            │
│   Mic click                                                │
│     → getUserMedia() → MediaStream                         │
│     → AudioContext → AnalyserNode → waveform loop (rAF)   │
│     → SpeechRecognition.start()                            │
│          → onresult → accumulate final transcript          │
│          → onend → fill #cmdInput → transitionToIdle()     │
│     → user clicks Send (existing handler)                  │
│                                                            │
│   sendCommand() [UNCHANGED]                                │
│     → ws.send({type:'command', text})                      │
└──────────────────────────────────────────────────────────┘
                          │ WebSocket (unchanged)
                          ▼
┌──────────────────────────────────────────────────────────┐
│ dashboard_server.py [UNCHANGED]                            │
│   WS `command` handler → publish_command(text)             │
│     → /user_input ROS topic                                │
└──────────────────────────────────────────────────────────┘
                          │ ROS (unchanged)
                          ▼
┌──────────────────────────────────────────────────────────┐
│ llm_planner_node [UNCHANGED]                               │
│   Subscribes /user_input, runs LLM planner, executes       │
└──────────────────────────────────────────────────────────┘
```

### 3.2 State Machine

```
       ┌──────────┐
       │   IDLE   │◄──────────────┐
       └─────┬────┘                │
             │ click mic            │ transitionToIdle()
             ▼                     │ (from any exit path)
       ┌──────────┐                │
       │ RECORDING │────────────────┘
       └──────────┘
        Exit paths (all funnel through transitionToIdle):
          • Stop button                → fill input with transcript, then idle
          • Auto-stop on silence       → fill input with transcript, then idle
          • Cancel button              → discard transcript (input unchanged), then idle
          • Esc keypress               → same as Cancel
          • recognition.onerror        → toast (if not silent code), then idle
          • getUserMedia rejection     → toast, then idle
```

**Invariant:** `transitionToIdle()` is idempotent — re-entry from race conditions (e.g., `onerror` firing after manual Cancel) is a no-op.

## 4. HTML Structure

### 4.1 Input Area Changes

The existing `.input-area` at lines 418–422 of `index.html` is replaced with a two-row swap container. Only one row is visible at a time.

```html
<div class="input-area">
  <!-- Idle state: shown by default -->
  <div class="input-row" id="inputRow">
    <button class="icon-btn mic-btn" id="micBtn" title="Voice input">
      <svg><!-- mic icon --></svg>
    </button>
    <input type="text" id="cmdInput" placeholder="Type a command..." autocomplete="off">
    <button id="sendBtn" onclick="sendCommand()">Send</button>
  </div>

  <!-- Recording state: hidden by default -->
  <div class="recording-row" id="recordingRow" style="display:none">
    <button class="icon-btn cancel-btn" id="cancelBtn" title="Cancel (Esc)">Cancel</button>
    <div class="waveform-container">
      <span class="rec-dot"></span>
      <canvas id="waveformCanvas" width="240" height="36"></canvas>
    </div>
    <button class="icon-btn stop-btn" id="stopBtn" title="Stop recording">Stop</button>
  </div>
</div>

<!-- Toast container (new, at end of <body>) -->
<div class="toast-container" id="toastContainer"></div>
```

### 4.2 New Element IDs

| ID | Purpose |
|----|---------|
| `inputRow` | Idle-state row wrapper (swap target) |
| `recordingRow` | Recording-state row wrapper (swap target) |
| `micBtn` | Mic button, starts recording |
| `cancelBtn` | Cancels recording, discards transcript |
| `stopBtn` | Stops recording, fills transcript into input |
| `waveformCanvas` | Live waveform drawing surface |
| `toastContainer` | Vertical stack for error toasts |

## 5. CSS

~80 lines added, using the existing dashboard color palette (no new CSS variables).

Key rules:

- `.mic-btn` — circular 36×36 icon button, subtle hover state, matches `.send` button height
- `.recording-row` — same height as `.input-row`, flexbox with gap, **red-tinted background** (`rgba(220, 53, 69, 0.12)`) to signal active recording
- `.rec-dot` — 8px solid red circle with pulsing animation (`@keyframes rec-pulse`)
- `.waveform-container` — flex:1, centers canvas, no overflow
- `#waveformCanvas` — stroke color matches dashboard accent, background transparent
- `.cancel-btn` / `.stop-btn` — match existing button sizing, minimum tap target 32px
- `.toast-container` — fixed top-right, flex-column, gap 8px, z-index above modals
- `.toast` — dark background, white text, 3s fade-out animation, max-width 320px
- `.icon-btn:disabled` — reduced opacity, `cursor: not-allowed` (for browsers without SpeechRecognition)

**No layout shift** between idle and recording rows: both rows have matching `min-height`, ensuring content below (Navigate-to buttons, etc.) does not jump.

## 6. JavaScript

~135 lines added in a single `<script>` block near the existing `sendCommand()` function, organized into 7 sub-sections.

### 6.1 Module-level state

```js
let recognition = null;       // SpeechRecognition instance (lazy init)
let isRecording = false;      // state machine flag
let mediaStream = null;       // MediaStream from getUserMedia
let audioCtx = null;          // AudioContext
let analyser = null;          // AnalyserNode for waveform
let rafId = null;             // requestAnimationFrame handle
let finalTranscript = '';     // accumulated final results
```

### 6.2 Sub-sections

| Sub-section | Functions | Purpose |
|-------------|-----------|---------|
| A. Feature detection | `hasSpeechRecognition()` | Check `SpeechRecognition` / `webkitSpeechRecognition`; disable mic button + tooltip if missing |
| B. Initialization | `initRecognition()` | Lazy-create `SpeechRecognition`, set `lang='en-US'`, `continuous=false`, `interimResults=true`, wire up event handlers |
| C. Start flow | `startRecording()` | Guard against re-entry, request mic via `getUserMedia`, start waveform, start recognition, swap to recording row |
| D. Waveform | `startWaveform(stream)`, `drawWaveform()`, `stopWaveform()` | AudioContext setup, rAF draw loop, clean teardown |
| E. Stop flow | `handleRecognitionEnd()` | Fill `#cmdInput` with `finalTranscript`, call `transitionToIdle()` |
| F. Cancel flow | `cancelRecording()` | Call `recognition.abort()` (discards in-flight results), call `transitionToIdle()` without filling input |
| G. Cleanup | `transitionToIdle()` | Idempotent teardown: stop rAF, close AudioContext, stop MediaStream tracks, swap DOM rows. Safe to call multiple times. |

### 6.3 Event wiring

```js
micBtn.addEventListener('click', startRecording);
cancelBtn.addEventListener('click', cancelRecording);
stopBtn.addEventListener('click', () => recognition.stop());  // triggers onend → handleRecognitionEnd
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && isRecording) cancelRecording();
});
```

### 6.4 Recognition event handlers

```js
recognition.onresult = (event) => {
  for (let i = event.resultIndex; i < event.results.length; i++) {
    if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript;
  }
};

recognition.onend = () => {
  if (!isRecording) return;  // race guard: already cancelled
  if (finalTranscript.trim()) {
    document.getElementById('cmdInput').value = finalTranscript.trim();
  }
  transitionToIdle();
};

recognition.onerror = (event) => {
  const silentCodes = ['no-speech', 'aborted'];
  if (!silentCodes.includes(event.error)) {
    showToast(errorMessageFor(event.error));
  }
  transitionToIdle();
};
```

### 6.5 Reuse from `speech_web_ui/static/index.html`

| Function | Lines (source) | Action |
|----------|----------------|--------|
| Capability detection | 587–591 | **Direct copy** (trivial) |
| `onresult` interim/final splitter | 614–627 | **Direct copy** |
| `startWaveform()` | 687–712 | **Copy, adapt color to dashboard accent** |
| `drawWaveform()` | 714–745 | **Copy unchanged** |
| `stopWaveform()` | 747–768 | **Copy unchanged** |

The `onend` handler and UI swap logic are **new** — `speech_web_ui` auto-sends on end, whereas the dashboard must only fill the input.

## 7. Error Handling

### 7.1 Error Categories

| # | Source | Trigger | User-visible? | Action |
|---|--------|---------|---------------|--------|
| E1 | `SpeechRecognition` API missing | Firefox / old browser on load | Toast on first click, button disabled afterward | No state change (never entered RECORDING) |
| E2 | `getUserMedia` rejected — `NotAllowedError` | User denied mic permission | Toast: "Microphone access denied" | `transitionToIdle()` |
| E3 | `getUserMedia` rejected — `NotFoundError` | No mic hardware | Toast: "No microphone found" | `transitionToIdle()` |
| E4 | `getUserMedia` rejected — other | Hardware busy, OS error | Toast: "Microphone unavailable" | `transitionToIdle()` |
| E5 | `recognition.onerror` — `network` | Chrome speech backend unreachable | Toast: "Speech service unreachable" | `transitionToIdle()` |
| E6 | `recognition.onerror` — `not-allowed` | Permission revoked mid-session | Toast: "Microphone access denied" | `transitionToIdle()` |
| E7 | `recognition.onerror` — `audio-capture` | Device disconnected mid-record | Toast: "Microphone disconnected" | `transitionToIdle()` |
| E8 | `recognition.onerror` — `no-speech` | Auto-stop on silence (**expected**) | **Silent** | `transitionToIdle()` |
| E9 | `recognition.onerror` — `aborted` | User clicked Cancel (**expected**) | **Silent** | `transitionToIdle()` |
| E10 | `AudioContext` constructor throws | Browser blocks before user gesture | Toast: "Audio unavailable" | `transitionToIdle()` |

**Silent codes** (`no-speech`, `aborted`) are expected flows and must NOT show a toast.

### 7.2 Race Conditions

| Race | Scenario | Guard |
|------|----------|-------|
| R1 | Double-click mic button | `startRecording()` returns early if `isRecording === true` |
| R2 | Rapid Cancel → Esc → Cancel | `transitionToIdle()` is idempotent via `if (!isRecording) return` |
| R3 | `onerror` fires after manual cancel | Cancel calls `recognition.abort()` → `onerror('aborted')` → silent, idempotent cleanup |
| R4 | `onend` fires after manual cancel | Same idempotent guard — `onend` re-enters `transitionToIdle()` and exits |
| R5 | Stop button pressed while `onresult` pending | Final result arrives → `onend` fires → input filled normally |
| R6 | User switches tabs mid-record | Chrome pauses recognition → `onend` fires → normal Stop path |
| R7 | OS revokes mic mid-record | `onerror('audio-capture')` → E7 toast + cleanup |

### 7.3 Cleanup Contract

```
transitionToIdle():
  if (!isRecording) return           // idempotent guard
  isRecording = false                // flip state first
  try { recognition.abort() } catch {}
  try { cancelAnimationFrame(rafId) } catch {}
  try { audioCtx.close() } catch {}
  try { mediaStream.getTracks().forEach(t => t.stop()) } catch {}
  rafId = null; audioCtx = null; analyser = null; mediaStream = null
  finalTranscript = ''               // clear after last use
  swapToInputRow()                   // DOM swap back
```

Every exit path MUST call `transitionToIdle()`:

1. User clicks Stop → fills input with transcript, then `transitionToIdle()`
2. User clicks Cancel → leaves input unchanged, then `transitionToIdle()`
3. User presses Esc → same as Cancel
4. `recognition.onend` (auto-stop on silence) → fills input with transcript, then `transitionToIdle()`
5. `recognition.onerror` (any code) → `transitionToIdle()`, conditionally toast
6. `getUserMedia` rejection → `transitionToIdle()` + toast
7. WebSocket disconnect observed mid-record → no-op (recording continues; Send is separately gated)

### 7.4 Edge Cases

- **Input field already has text:** voice transcript **overwrites** existing text. Simpler mental model; matches Stop semantics.
- **WebSocket disconnect mid-record:** recording continues normally (client-only). On Stop, transcript fills input; existing `sendCommand()` guard (`ws.readyState !== 1`) blocks send.
- **Browser tab backgrounded:** Chrome suspends recognition → `onend` fires → transcript (possibly partial) fills input → UI returns to idle.
- **Multiple toasts:** `.toast-container` is a flex column; toasts stack vertically, each dismisses independently on its own 3s timer.
- **Stuck state recovery:** Esc always invokes idempotent `transitionToIdle()` — self-healing.

### 7.5 Explicitly Out of Scope

- Retry logic on `network` errors — user can just tap mic again
- Persistent "mic blocked" banner — one-time toast suffices
- Transcript correction UI beyond the existing input field
- Partial/interim transcript display — waveform is the live feedback channel
- Multi-language support

## 8. Testing & Verification Plan

Manual verification via checklist, grouped by category. No automated test harness exists for the dashboard.

### 8.1 Happy Path (blocks ship)

| # | Steps | Expected |
|---|-------|----------|
| H1 | Load dashboard | Mic button visible left of Send, text input unchanged |
| H2 | Click mic → grant permission | Row swaps: red dot, waveform animating, Cancel + Stop visible |
| H3 | Speak "go to table 3" → auto-stop on silence | Row swaps back, input shows "go to table 3", Send enabled |
| H4 | Click Send | Command dispatched via existing WebSocket path |
| H5 | Click mic → speak → click Stop before silence | Transcript fills input immediately, row returns to idle |
| H6 | Click mic → speak → click Cancel | Input remains empty, row returns to idle, no command sent |
| H7 | Click mic → speak → press Esc | Same as H6 |
| H8 | Click mic → stay silent ~3s (auto-stop) | Row returns to idle, input stays empty, no toast |

### 8.2 Error Paths

| # | Setup | Steps | Expected |
|---|-------|-------|----------|
| ET1 | Firefox | Load dashboard | Mic button disabled with tooltip; click shows "Voice input not supported in this browser" toast |
| ET2 | Chrome, deny mic at prompt | Click mic → deny | Toast: "Microphone access denied", row stays idle |
| ET3 | Permission previously denied | Click mic | Toast immediately (no prompt) |
| ET4 | Unplug USB mic after granting | Click mic → speak → unplug | Toast: "Microphone disconnected", row returns to idle |
| ET5 | Disconnect network | Click mic → speak | Toast: "Speech service unreachable", row returns to idle |

### 8.3 Race Conditions & Edge Cases

| # | Steps | Expected |
|---|-------|----------|
| RT1 | Double-click mic rapidly | Only one recording session starts |
| RT2 | Click mic → Cancel → immediately click mic | Clean second session, no stuck state |
| RT3 | Click mic → Cancel → Esc → Cancel spam | No console errors, idempotent |
| RT4 | Type "hello" → click mic → say "world" → Stop | Input shows "world" (overwrite confirmed) |
| RT5 | Stop dashboard server → click mic → speak → Stop | Transcript fills input, Send blocked by existing WS guard |
| RT6 | Click mic → switch tab 10s → switch back | Recording ended, transcript (if any) in input, idle state |
| RT7 | Trigger 3 errors rapidly (no mic, 3×) | 3 toasts stack vertically, each dismisses independently |

### 8.4 Cleanup Verification (DevTools)

| # | Steps | Check |
|---|-------|-------|
| CT1 | Performance Monitor → 10× record cycles | JS heap stable, node count stable |
| CT2 | `chrome://media-internals` after every exit path | No lingering active audio stream |
| CT3 | Console throughout all tests | No uncaught exceptions |
| CT4 | Memory snapshot before & after 20 cycles | No retained AudioContext / MediaStream / AnalyserNode |

### 8.5 Visual QA

| # | Check |
|---|-------|
| V1 | Mic icon renders (SVG stroke visible on dark background) |
| V2 | Recording row red accent matches dashboard palette |
| V3 | Waveform animates smoothly at ~60fps |
| V4 | Row swap causes no layout shift below |
| V5 | Cancel / Stop tap targets ≥32px |
| V6 | Toast does not obscure input or destination buttons |

### 8.6 Regression Checks

| # | Check |
|---|-------|
| G1 | Typing + Send still works identically |
| G2 | Enter key in text input still sends command |
| G3 | Destination buttons (Navigate to table_1…) still work |
| G4 | Preflight checks, map, deploy log, chat — all unchanged |
| G5 | Semantic map editor (add/edit/delete location) still works |

### 8.7 Ship Criteria

Sections **8.1, 8.2, 8.3, 8.6** must fully pass. Sections 8.4 and 8.5 are strong-recommend but not blocking. A console exception or obvious memory leak blocks; cosmetic imperfection does not.

## 9. Files Changed

- `dashboard/static/index.html` — single file, ~250 lines added (HTML + CSS + JS)

**Explicitly unchanged:**

- `dashboard/dashboard_server.py` — the WebSocket `command` handler at line 1911 already accepts `{type: 'command', text}` and publishes to `/user_input`. Voice transcripts travel this exact path.
- `campus_nav_llm/llm_planner_node.py` — subscribes to `/user_input`, unchanged.
- `config.yaml`, semantic map files — unrelated.

## 10. Open Questions

None. All design decisions resolved during brainstorming.

## 11. References

- Existing voice reference implementation: `speech_web_ui/static/index.html` (lines 587–768)
- Dashboard input area: `dashboard/static/index.html` lines 418–422
- WebSocket command handler (unchanged): `dashboard/dashboard_server.py:1911`
- Web Speech API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API
- Telegram voice message UI (visual reference for in-place transform)
