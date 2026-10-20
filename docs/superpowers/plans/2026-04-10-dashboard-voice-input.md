# Dashboard Voice Input & Waveform Visualizer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram-style voice/mic input button next to the dashboard text field. Clicking mic transforms the input row in place to a live waveform visualizer with Cancel/Stop controls, deposits the recognized transcript into the existing text input for user review before sending.

**Architecture:** Single-file feature — all changes in `dashboard/static/index.html`. Uses browser-native Web Speech API (`SpeechRecognition`) + Web Audio API (`AudioContext` + `AnalyserNode`). Zero server-side changes: the voice transcript fills `#cmdInput` and then travels through the already-working `sendCommand()` → WebSocket → `/user_input` ROS topic chain. Reuses `startWaveform` / `drawWaveform` / `stopWaveform` from the existing `speech_web_ui/static/index.html` reference implementation.

**Tech Stack:** Vanilla JavaScript, Web Speech API, Web Audio API, Canvas 2D, CSS3

**Spec:** `docs/superpowers/specs/2026-04-10-dashboard-voice-input-design.md`

**Testing strategy:** The dashboard has no automated test harness. Each task ends with a concrete manual browser verification step — reload the dashboard, execute the listed actions, confirm the listed expected behavior. Ship criteria live in the spec's Section 8.7.

**Precondition:** Before starting, ensure the dashboard is runnable locally:

```bash
cd /Users/XUETAO/Documents/course/CS5335/CS5335TurtleBot/dashboard
# In ROS mode (preferred for full regression check):
./run.sh
# OR demo mode (sufficient for UI-only verification):
python3 dashboard_server.py
```

Dashboard listens on `http://localhost:8000` (or whatever port `dashboard_server.py` binds). Use a Chromium-based browser (Chrome/Edge/Brave) — Firefox and Safari lack `SpeechRecognition` and will be verified separately in Task 12.

---

## File Structure

**Modified:** `dashboard/static/index.html` (one file, ~250 lines added)

Breakdown:
- HTML: ~20 lines in `<body>` (lines 418–422 replaced + toast container before `</body>`)
- CSS: ~80 lines inside existing `<style>` (after line 77)
- JS: ~150 lines inside existing `<script>` (new state block near line 428, new functions near line 785 before `sendCommand`, event wiring inside existing load handler near line 460)

**Unchanged (explicit):**
- `dashboard/dashboard_server.py` — the WS `command` handler already accepts `{type:'command', text}`
- `campus_guide_bot/campus_nav_llm/llm_planner_node.py` — subscribes to `/user_input`, unchanged
- `speech_web_ui/` — reference implementation, source of reused functions

---

## Task 1: Replace input-area HTML with two-row swap structure

**Files:**
- Modify: `dashboard/static/index.html:418-422`
- Modify: `dashboard/static/index.html` (add toast container before closing `</body>`)

- [ ] **Step 1: Locate the current input area**

Read `dashboard/static/index.html` lines 415–425 to confirm the exact structure. Expected content:

```html
    <!-- Chat -->
    <div class="chat-area" id="chatArea"></div>

    <!-- Input -->
    <div class="input-area">
      <input type="text" id="cmdInput" placeholder="Type a command..." autocomplete="off">
      <button id="sendBtn" onclick="sendCommand()">Send</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Replace the input-area block**

Replace lines 419–422 with the two-row swap structure:

```html
    <!-- Input -->
    <div class="input-area">
      <!-- Idle state: shown by default -->
      <div class="input-row" id="inputRow">
        <button class="icon-btn mic-btn" id="micBtn" type="button" title="Voice input" aria-label="Start voice input">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>
        <input type="text" id="cmdInput" placeholder="Type a command..." autocomplete="off">
        <button id="sendBtn" onclick="sendCommand()">Send</button>
      </div>

      <!-- Recording state: hidden by default -->
      <div class="recording-row" id="recordingRow" style="display:none">
        <button class="icon-btn cancel-btn" id="cancelBtn" type="button" title="Cancel (Esc)">Cancel</button>
        <div class="waveform-container">
          <span class="rec-dot"></span>
          <canvas id="waveformCanvas" width="180" height="32"></canvas>
        </div>
        <button class="icon-btn stop-btn" id="stopBtn" type="button" title="Stop recording">Stop</button>
      </div>
    </div>
```

- [ ] **Step 3: Add toast container at end of body**

Find the closing `</body>` tag (near the end of the file). Immediately before it, add:

```html
<!-- Toast container for voice input errors -->
<div class="toast-container" id="toastContainer"></div>
</body>
```

- [ ] **Step 4: Manual verification — page still loads**

Reload `http://localhost:8000` in Chrome. Expected:
- Page loads without any console errors
- Microphone icon button is visible to the left of the text input
- Text input + Send button still look and function normally
- Typing a command and pressing Enter or Send still works (existing regression check)
- Right-clicking the mic button does nothing unusual (no context menu hijack)

The mic button has no click handler yet — clicking it should do nothing. This is expected.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add mic button + recording row HTML scaffolding

Replaces input-area with a two-row swap structure: idle row
(mic button + text input + Send) and recording row (Cancel +
waveform canvas + Stop), plus a toast container. No behavior
yet — clicking mic is a no-op.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: CSS — input row layout + icon button base + mic button

**Files:**
- Modify: `dashboard/static/index.html` (add rules after line 77, inside `<style>`)

- [ ] **Step 1: Locate the current input-area CSS**

Read `dashboard/static/index.html` lines 72–78. Expected:

```css
/* Input area */
.input-area { padding: 10px 14px; border-top: 1px solid #1e2a3a; display: flex; gap: 8px; }
.input-area input { flex: 1; background: #131820; border: 1px solid #1e2a3a; border-radius: 8px; padding: 8px 12px; color: #e0e6ed; font-size: 13px; outline: none; }
.input-area input:focus { border-color: #00d4ff; }
.input-area button { background: #00d4ff; color: #000; border: none; border-radius: 8px; padding: 8px 16px; font-weight: 600; font-size: 13px; cursor: pointer; }
.input-area button:hover { background: #33ddff; }
```

- [ ] **Step 2: Adjust .input-area to be a flex column container**

The `.input-area` wrapper must allow either the idle row or the recording row to occupy the row. Change its `display: flex` (which was for inline children) to something that works for both rows.

Update `.input-area` on line 73:

```css
.input-area { padding: 10px 14px; border-top: 1px solid #1e2a3a; }
```

(Remove `display: flex; gap: 8px;` from `.input-area` — flex moves to the inner rows.)

The existing `.input-area input` / `.input-area button` selectors still apply (they target descendants), so the text input and Send button keep their look without change.

- [ ] **Step 3: Add input-row / recording-row wrapper styles**

Add immediately after the existing `.input-area button:hover` rule (line 77):

```css
/* Voice input: row wrappers (inside .input-area) */
.input-row, .recording-row { display: flex; gap: 8px; align-items: center; min-height: 38px; }

/* Icon button base (used by mic, cancel, stop) */
.icon-btn { background: #131820; border: 1px solid #1e2a3a; border-radius: 8px; color: #8899aa; cursor: pointer; font-size: 12px; font-weight: 600; padding: 0; display: inline-flex; align-items: center; justify-content: center; transition: all 0.15s; }
.icon-btn:hover { border-color: #00d4ff; color: #00d4ff; }
.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.icon-btn:disabled:hover { border-color: #1e2a3a; color: #8899aa; }

/* Mic button specifically */
.mic-btn { width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; }
.mic-btn svg { width: 18px; height: 18px; }
```

- [ ] **Step 4: Manual verification — visual**

Reload the dashboard. Expected:
- Mic button is a 36×36 dark circle with a cyan-on-hover microphone SVG icon
- Text input flows naturally to the right of the mic button, Send button on the far right
- Hovering over the mic button changes its border and icon color to cyan (`#00d4ff`)
- No layout shift — the input area is the same vertical position as before
- Send button still works, Enter key still sends

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "style(dashboard): add CSS for mic button + input row wrappers

Voice input row layout: .input-row / .recording-row flex wrappers,
.icon-btn base style, .mic-btn circular 36x36.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: CSS — recording row, rec-dot pulse, waveform container

**Files:**
- Modify: `dashboard/static/index.html` (add rules after the CSS added in Task 2)

- [ ] **Step 1: Add recording row styles**

Add immediately after the `.mic-btn svg` rule from Task 2:

```css
/* Recording row: red-tinted, shows during voice capture */
.recording-row { background: rgba(220, 53, 69, 0.12); border: 1px solid rgba(220, 53, 69, 0.3); border-radius: 8px; padding: 4px 8px; }
.recording-row .cancel-btn { padding: 6px 12px; border-color: rgba(220, 53, 69, 0.4); color: #ff8899; }
.recording-row .cancel-btn:hover { border-color: #ff4466; color: #ff4466; }
.recording-row .stop-btn { padding: 6px 12px; border-color: rgba(0, 212, 255, 0.4); color: #00d4ff; }
.recording-row .stop-btn:hover { border-color: #00d4ff; color: #33ddff; background: rgba(0, 212, 255, 0.1); }

/* Pulsing red dot (recording indicator) */
.rec-dot { width: 8px; height: 8px; border-radius: 50%; background: #ff4466; flex-shrink: 0; animation: rec-pulse 1.2s ease-in-out infinite; }
@keyframes rec-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

/* Waveform container holds the dot + canvas, fills middle of recording row */
.waveform-container { flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; }
#waveformCanvas { flex: 1; height: 32px; display: block; }
```

- [ ] **Step 2: Manual verification — temporarily force recording row visible**

Open DevTools console and run:

```js
document.getElementById('inputRow').style.display = 'none';
document.getElementById('recordingRow').style.display = 'flex';
```

Expected:
- Recording row appears in place of the idle row
- Red-tinted background visible
- Red dot pulsing on the left of the waveform area
- Cancel button on far left, Stop button on far right
- Empty canvas area between them (no waveform drawn yet — that comes in Task 7)

Then restore:

```js
document.getElementById('inputRow').style.display = 'flex';
document.getElementById('recordingRow').style.display = 'none';
```

Expected: back to normal idle state.

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "style(dashboard): add recording row, pulsing dot, waveform layout

Red-tinted recording row with Cancel/Stop buttons framing a
pulsing rec-dot and waveform canvas.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: CSS — toast container + toast animations

**Files:**
- Modify: `dashboard/static/index.html` (append to `<style>` block after Task 3 rules)

- [ ] **Step 1: Add toast styles**

Add immediately after the `#waveformCanvas` rule from Task 3:

```css
/* Toast notifications (voice input errors) */
.toast-container { position: fixed; top: 60px; right: 16px; display: flex; flex-direction: column; gap: 8px; z-index: 1000; pointer-events: none; }
.toast { background: #1a1f2e; border: 1px solid #2e0a0a; border-left: 3px solid #ff4466; border-radius: 6px; padding: 10px 14px; color: #e0e6ed; font-size: 12px; max-width: 300px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); animation: toast-in 0.2s ease-out, toast-out 0.3s ease-in 2.7s forwards; pointer-events: auto; }
@keyframes toast-in {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes toast-out {
  from { opacity: 1; transform: translateX(0); }
  to   { opacity: 0; transform: translateX(20px); }
}
```

Total toast lifetime: 0.2s fade in + 2.5s hold + 0.3s fade out = 3.0s.

- [ ] **Step 2: Manual verification — temporary toast injection**

Open DevTools console and run:

```js
const t = document.createElement('div');
t.className = 'toast';
t.textContent = 'Test toast message';
document.getElementById('toastContainer').appendChild(t);
```

Expected:
- Toast appears in top-right corner below the header
- Slides in from the right, fully visible for ~2.5s
- Fades out and slides back to the right after 3s total
- Toast element is still in the DOM after animation (will be removed by JS in Task 6)

Manually remove the leftover element:

```js
document.querySelectorAll('#toastContainer .toast').forEach(e => e.remove());
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "style(dashboard): add toast container and slide-in/out animations

Top-right stacked toast notifications with 3s auto-fade for
voice input error messages.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: JS — state variables, feature detection, toast helper

**Files:**
- Modify: `dashboard/static/index.html` (add inside `<script>` block, after the existing state block near line 436)

- [ ] **Step 1: Locate the existing state block**

Read `dashboard/static/index.html` lines 426–440. Expected:

```js
<script>
// ── State ──
let ws = null;
let mapInfo = null;
let mapImg = null;
let robotPose = { px: 0, py: 0, theta: 0, x: 0, y: 0 };
let locations = {};
let canvas, ctx;
let demoMode = true;
let navStartDist = 0;
```

- [ ] **Step 2: Append voice state block**

Add these lines immediately after `let navStartDist = 0;`:

```js

// ── Voice input state ──
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;       // SpeechRecognition instance (lazy init)
let isRecording = false;      // state machine flag
let mediaStream = null;       // MediaStream from getUserMedia
let audioCtx = null;          // AudioContext
let analyser = null;          // AnalyserNode for waveform
let rafId = null;             // requestAnimationFrame handle
let finalTranscript = '';     // accumulated final recognition results
```

- [ ] **Step 3: Add the toast helper function**

Scroll to just above the `sendCommand()` function (near line 785). Add this block immediately before `function sendCommand()`:

```js
// ── Voice input: toast helper ──
function showToast(message) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  // CSS animation runs for 3s total, then remove from DOM
  setTimeout(() => { toast.remove(); }, 3100);
}
```

- [ ] **Step 4: Add feature-detection wiring inside the load handler**

Find the existing load handler at line 438 and the line that reads `connectWS();` (near line 459). Immediately after `connectWS();`, add:

```js

  // Voice input: disable mic button if SpeechRecognition not supported
  const micBtn = document.getElementById('micBtn');
  if (!SpeechRec) {
    micBtn.disabled = true;
    micBtn.title = 'Voice input not supported in this browser';
  }
```

- [ ] **Step 5: Manual verification**

Reload the dashboard in Chrome. Open DevTools console and run:

```js
console.log('SpeechRec:', !!SpeechRec);
console.log('isRecording:', isRecording);
showToast('Hello from voice feature');
```

Expected:
- `SpeechRec: true` (in Chrome)
- `isRecording: false`
- A toast appears in the top-right saying "Hello from voice feature" and fades after 3s
- The toast DOM element is removed from `#toastContainer` after ~3.1s (check with `document.querySelectorAll('#toastContainer .toast').length` → should return 0)

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add voice input state + toast helper + feature detect

Module-level state variables for SpeechRecognition lifecycle,
showToast() helper with 3.1s DOM cleanup, and browser-capability
check that disables the mic button on unsupported browsers.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: JS — waveform functions (start, draw, stop)

**Files:**
- Modify: `dashboard/static/index.html` (add functions after `showToast`)

- [ ] **Step 1: Add waveform functions**

Add immediately after the `showToast` function from Task 5:

```js
// ── Voice input: waveform visualizer ──
async function startWaveform() {
  // Reuses getUserMedia stream if already obtained by startRecording.
  // Caller (startRecording) passes the stream in via module state.
  if (!mediaStream) return;
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    const src = audioCtx.createMediaStreamSource(mediaStream);
    src.connect(analyser);
    drawWaveform();
  } catch (e) {
    console.warn('Waveform init failed:', e);
    // Non-fatal: recording continues without visual feedback
  }
}

function drawWaveform() {
  const c = document.getElementById('waveformCanvas');
  if (!c) return;
  const cctx = c.getContext('2d');
  const W = c.width = c.offsetWidth;
  const H = c.height = c.offsetHeight;

  const bufLen = analyser ? analyser.frequencyBinCount : 128;
  const data = new Uint8Array(bufLen);

  function frame() {
    rafId = requestAnimationFrame(frame);
    if (analyser) analyser.getByteTimeDomainData(data);

    cctx.clearRect(0, 0, W, H);

    // Background gradient (cyan at center, fade at edges)
    const grad = cctx.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, 'transparent');
    grad.addColorStop(0.3, 'rgba(0,212,255,0.06)');
    grad.addColorStop(0.7, 'rgba(0,212,255,0.06)');
    grad.addColorStop(1, 'transparent');
    cctx.fillStyle = grad;
    cctx.fillRect(0, 0, W, H);

    // Waveform line
    cctx.beginPath();
    cctx.strokeStyle = '#00d4ff';
    cctx.lineWidth = 2;
    cctx.shadowBlur = 6;
    cctx.shadowColor = '#00d4ff';

    const sliceW = W / bufLen;
    let x = 0;
    for (let i = 0; i < bufLen; i++) {
      const v = analyser ? (data[i] / 128.0) : (Math.sin((Date.now() / 600) + i * 0.2) * 0.08 + 1);
      const y = (v * H / 2);
      i === 0 ? cctx.moveTo(x, y) : cctx.lineTo(x, y);
      x += sliceW;
    }
    cctx.stroke();
  }
  frame();
}

function stopWaveform() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  if (audioCtx) {
    try { audioCtx.close(); } catch (e) {}
    audioCtx = null;
  }
  analyser = null;
}
```

- [ ] **Step 2: Manual verification — waveform in isolation**

Reload the dashboard. Open DevTools console and run this test sequence:

```js
// Manually acquire a mic stream and draw the waveform
(async () => {
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  // Show recording row so the canvas is visible and has dimensions
  document.getElementById('inputRow').style.display = 'none';
  document.getElementById('recordingRow').style.display = 'flex';
  await startWaveform();
  console.log('Waveform started — speak into the mic');
})();
```

Expected:
- Browser prompts for microphone permission (grant it)
- Red dot pulses in the recording row
- Waveform canvas shows a cyan oscilloscope-style line that reacts to your voice
- Speaking into the mic causes visible waveform deflection
- Line is smooth (no stuttering at ~60fps)

Then clean up:

```js
stopWaveform();
mediaStream.getTracks().forEach(t => t.stop());
mediaStream = null;
document.getElementById('inputRow').style.display = 'flex';
document.getElementById('recordingRow').style.display = 'none';
```

Expected:
- Waveform animation stops
- Mic indicator in browser tab disappears (stream released)
- UI returns to idle

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add waveform visualizer functions

startWaveform() wires an AnalyserNode to the existing mediaStream,
drawWaveform() renders a cyan oscilloscope via requestAnimationFrame,
stopWaveform() tears down the AudioContext and cancels the rAF loop.
Adapted from speech_web_ui reference implementation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: JS — transitionToIdle cleanup contract

**Files:**
- Modify: `dashboard/static/index.html` (add function after `stopWaveform`)

- [ ] **Step 1: Add the centralized cleanup function**

Add immediately after `stopWaveform`:

```js
// ── Voice input: centralized idempotent cleanup ──
// Every exit path from RECORDING state funnels through here.
// Safe to call multiple times — race-condition re-entry is a no-op.
function transitionToIdle() {
  if (!isRecording) return;       // idempotent guard
  isRecording = false;             // flip state flag first

  // Abort recognition (triggers onerror('aborted') → silent path)
  if (recognition) {
    try { recognition.abort(); } catch (e) {}
  }

  // Stop waveform rendering + close AudioContext
  stopWaveform();

  // Release the microphone
  if (mediaStream) {
    try { mediaStream.getTracks().forEach(t => t.stop()); } catch (e) {}
    mediaStream = null;
  }

  // Clear accumulated transcript (it has been consumed by the caller if needed)
  finalTranscript = '';

  // Swap DOM back to idle row
  const inputRow = document.getElementById('inputRow');
  const recordingRow = document.getElementById('recordingRow');
  if (inputRow) inputRow.style.display = 'flex';
  if (recordingRow) recordingRow.style.display = 'none';
}
```

- [ ] **Step 2: Manual verification — idempotency + no-op when already idle**

Reload the dashboard. Open DevTools console and run:

```js
// Call from idle state — should be a no-op, no errors
transitionToIdle();
console.log('After 1st call — isRecording:', isRecording);  // expected: false

// Simulate recording state and then cleanup
isRecording = true;
document.getElementById('inputRow').style.display = 'none';
document.getElementById('recordingRow').style.display = 'flex';

transitionToIdle();
console.log('After 2nd call — isRecording:', isRecording);  // expected: false
console.log('inputRow display:', document.getElementById('inputRow').style.display);  // expected: "flex"
console.log('recordingRow display:', document.getElementById('recordingRow').style.display);  // expected: "none"

// Call again — should still be a no-op
transitionToIdle();
console.log('After 3rd call — still idle');
```

Expected:
- No console errors on any of the three calls
- After call 2, DOM is visibly back to idle row
- No leaked state

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add transitionToIdle centralized cleanup contract

Idempotent teardown funnel for all voice-recording exit paths.
Aborts recognition, stops waveform, releases mic stream, clears
transcript buffer, and swaps the DOM back to the idle row.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: JS — initRecognition() with event handlers

**Files:**
- Modify: `dashboard/static/index.html` (add function after `transitionToIdle`)

- [ ] **Step 1: Add error-message mapping helper and initRecognition**

Add immediately after `transitionToIdle`:

```js
// ── Voice input: map recognition error codes to user-friendly messages ──
function errorMessageFor(code) {
  switch (code) {
    case 'network':       return 'Speech service unreachable. Check your internet.';
    case 'not-allowed':   return 'Microphone access denied.';
    case 'audio-capture': return 'Microphone disconnected.';
    case 'service-not-allowed': return 'Speech service blocked by browser.';
    default:              return 'Voice input error: ' + code;
  }
}

// ── Voice input: lazy-create the SpeechRecognition instance ──
function initRecognition() {
  if (recognition) return recognition;  // already initialized
  if (!SpeechRec) return null;

  const r = new SpeechRec();
  r.continuous = false;
  r.lang = 'en-US';
  r.interimResults = true;   // kept true to match reference; only isFinal results are consumed
  r.maxAlternatives = 1;

  r.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      }
    }
  };

  r.onend = () => {
    // Race guard: if already cancelled, don't touch the input
    if (!isRecording) return;
    const text = finalTranscript.trim();
    if (text) {
      document.getElementById('cmdInput').value = text;
    }
    transitionToIdle();
  };

  r.onerror = (event) => {
    // Expected/silent codes: do not show a toast
    const silentCodes = ['no-speech', 'aborted'];
    if (!silentCodes.includes(event.error)) {
      showToast(errorMessageFor(event.error));
    }
    // 'no-speech' on auto-stop: still keep any partial transcript
    if (event.error === 'no-speech' && isRecording) {
      const text = finalTranscript.trim();
      if (text) document.getElementById('cmdInput').value = text;
    }
    transitionToIdle();
  };

  recognition = r;
  return r;
}
```

- [ ] **Step 2: Manual verification**

Reload the dashboard. Open DevTools console:

```js
const r = initRecognition();
console.log('recognition:', r);
console.log('lang:', r.lang);                     // expected: "en-US"
console.log('continuous:', r.continuous);          // expected: false
console.log('interimResults:', r.interimResults);  // expected: true
console.log('handlers wired:', !!r.onresult && !!r.onend && !!r.onerror);  // expected: true
```

Expected: all values match. No DOM changes yet — this only lazy-constructs the recognition object. Starting/stopping it happens in Task 9.

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add SpeechRecognition init + event handlers

initRecognition() lazy-creates the recognition instance with
onresult (accumulates finalTranscript), onend (fills #cmdInput
and transitions to idle), and onerror (maps codes to toasts,
silences no-speech/aborted). Adds errorMessageFor() helper.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: JS — startRecording and cancelRecording

**Files:**
- Modify: `dashboard/static/index.html` (add functions after `initRecognition`)

- [ ] **Step 1: Add the start and cancel flow functions**

Add immediately after `initRecognition`:

```js
// ── Voice input: start the recording flow ──
async function startRecording() {
  if (isRecording) return;  // guard against double-click
  if (!SpeechRec) {
    showToast('Voice input not supported in this browser');
    return;
  }

  // Reset transcript buffer defensively
  finalTranscript = '';

  // Acquire microphone FIRST — if this fails, show toast and stay idle
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    if (err.name === 'NotAllowedError') {
      showToast('Microphone access denied');
    } else if (err.name === 'NotFoundError') {
      showToast('No microphone found');
    } else {
      showToast('Microphone unavailable');
    }
    return;
  }

  // Flip state and swap DOM
  isRecording = true;
  document.getElementById('inputRow').style.display = 'none';
  document.getElementById('recordingRow').style.display = 'flex';

  // Start waveform visualizer (uses module-level mediaStream)
  await startWaveform();

  // Start speech recognition
  const r = initRecognition();
  try {
    r.start();
  } catch (e) {
    console.warn('recognition.start() failed:', e);
    showToast('Could not start voice recognition');
    transitionToIdle();
  }
}

// ── Voice input: cancel flow (discards transcript) ──
// transitionToIdle() already calls recognition.abort() which triggers
// onerror('aborted') on the silent path. No need to duplicate here.
function cancelRecording() {
  transitionToIdle();
}
```

- [ ] **Step 2: Verify no syntax errors**

Reload the dashboard. Check the DevTools console — there should be NO parse errors. Run:

```js
console.log('startRecording:', typeof startRecording);  // expected: "function"
console.log('cancelRecording:', typeof cancelRecording); // expected: "function"
```

Clicking the mic button still does nothing (handlers wire up in Task 10).

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add startRecording and cancelRecording

startRecording() acquires mic via getUserMedia (with error
toasts), swaps DOM rows, starts waveform + recognition.
cancelRecording() aborts recognition and funnels through
transitionToIdle() for cleanup.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 10: JS — wire event handlers (mic click, cancel, stop, Esc)

**Files:**
- Modify: `dashboard/static/index.html` (inside the load handler, around line 460)

- [ ] **Step 1: Locate the feature-detection wiring from Task 5**

Read the section added in Task 5, Step 4. It looks like:

```js
  connectWS();

  // Voice input: disable mic button if SpeechRecognition not supported
  const micBtn = document.getElementById('micBtn');
  if (!SpeechRec) {
    micBtn.disabled = true;
    micBtn.title = 'Voice input not supported in this browser';
  }
```

- [ ] **Step 2: Append the event wiring**

Change the block to:

```js
  connectWS();

  // Voice input: disable mic button if SpeechRecognition not supported
  const micBtn = document.getElementById('micBtn');
  if (!SpeechRec) {
    micBtn.disabled = true;
    micBtn.title = 'Voice input not supported in this browser';
  }

  // Voice input: event handlers
  micBtn.addEventListener('click', () => {
    if (!SpeechRec) {
      showToast('Voice input not supported in this browser');
      return;
    }
    startRecording();
  });
  document.getElementById('cancelBtn').addEventListener('click', cancelRecording);
  document.getElementById('stopBtn').addEventListener('click', () => {
    // Stop signals the recognizer to finalize — onend will fill the input
    if (recognition && isRecording) {
      try { recognition.stop(); } catch (e) {}
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isRecording) cancelRecording();
  });
```

- [ ] **Step 3: Manual verification — full happy path**

Reload the dashboard. Execute the happy path from spec Section 8.1:

1. Click the mic button. Browser prompts for mic permission — grant it.
   - Expected: row swaps to recording state (red-tinted, red dot pulsing, waveform animating)
2. Say "go to table 3" clearly, then stop speaking.
   - Expected: after ~1–2s of silence, row swaps back and text input shows "go to table 3" (Chrome auto-stops via `continuous=false`)
3. Click Send.
   - Expected: command is dispatched via existing WS path. In ROS mode, the robot begins navigation. In demo mode, a simulated response appears.
4. Click mic → speak → click Stop before silence.
   - Expected: transcript fills input immediately
5. Click mic → speak → click Cancel.
   - Expected: row returns to idle, input remains empty (or keeps any prior text untouched)
6. Click mic → speak → press Esc.
   - Expected: same as Cancel
7. Click mic → stay silent ~3s (auto-stop).
   - Expected: row returns to idle, input stays empty, NO toast (no-speech is silent)

If all 7 pass, the feature is functionally complete.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): wire voice input event handlers

Mic button click → startRecording, Cancel → cancelRecording,
Stop → recognition.stop() (triggers onend flow), Esc → cancel.
Feature is now functionally complete end-to-end.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Manual verification — error paths and race conditions

This task is verification-only. No code changes unless a test surfaces a bug. Run each check and confirm the expected behavior. If any fails, stop and fix the root cause before proceeding.

**Files (verification target):**
- `dashboard/static/index.html` (no changes expected)

- [ ] **Step 1: Error path ET2 — permission denied at prompt**

Open Chrome in a fresh incognito window, navigate to the dashboard, click mic, click "Block" on the permission prompt.

Expected: Toast "Microphone access denied", row stays idle.

- [ ] **Step 2: Error path ET3 — previously denied permission**

With permission already denied, click mic again.

Expected: Toast "Microphone access denied" appears immediately (no prompt this time). Row stays idle.

Reset the permission via the site-info button in the address bar for subsequent tests.

- [ ] **Step 3: Error path ET5 — network disconnect**

Grant mic permission. Open DevTools → Network tab → set to "Offline". Click mic → speak.

Expected: Toast "Speech service unreachable. Check your internet." Row returns to idle. (Note: Chrome's SpeechRecognition requires a network connection to Google's backend.)

Restore network.

- [ ] **Step 4: Race R1 — double-click mic button rapidly**

Click mic twice in rapid succession.

Expected: Only one recording session starts. No errors in console. Only one mic permission prompt (if not yet granted).

- [ ] **Step 5: Race R2 — rapid Cancel → mic → Cancel cycle**

Click mic → grant → Cancel → immediately click mic again → Cancel.

Expected: Clean second session starts, cancels cleanly. No stuck state. No console errors.

- [ ] **Step 6: Race R3 — Cancel/Esc spam**

Click mic → speak briefly → press Esc rapidly 5 times in a row.

Expected: No console errors. State returns to idle and stays idle.

- [ ] **Step 7: Edge case — overwrite existing input text**

Type "hello world" in the input field. Click mic → say "go to front door" → click Stop.

Expected: Input now shows "go to front door" (voice transcript overwrote the typed text).

- [ ] **Step 8: Edge case — tab backgrounding**

Click mic → grant → switch to another browser tab for 10 seconds → switch back.

Expected: Recognition has auto-ended. UI is back to idle. Input may contain partial transcript (OK) or be empty (OK). No console errors.

- [ ] **Step 9: Edge case — toast stacking**

In Firefox (or Chrome with mic permanently blocked): click mic 3 times in quick succession.

Expected: 3 toasts stack vertically in the top-right. Each dismisses on its own 3s timer.

- [ ] **Step 10: Cleanup verification (DevTools)**

Open DevTools → Performance Monitor (three-dot menu → More tools → Performance monitor). Note the JS heap size and DOM node count.

Perform 10 complete record cycles: click mic → speak → Stop → Send (empty text OK since sendCommand guards empty).

Expected:
- JS heap does not grow unboundedly (should stay within ±1MB of baseline)
- DOM node count returns to baseline after each cycle
- No console exceptions anywhere

Also check `chrome://media-internals` in a second tab. After the final cycle, no active audio streams should be listed for the dashboard tab.

- [ ] **Step 11: Firefox check — API unavailable path**

Open the dashboard in Firefox (Firefox does NOT ship `SpeechRecognition`).

Expected: Mic button is visible but disabled (reduced opacity, `cursor: not-allowed`). Tooltip on hover: "Voice input not supported in this browser". Clicking does nothing (or shows a toast — see implementation).

Note: there's a subtle choice here. In Task 10, the click handler shows a toast if `!SpeechRec`. But Task 5 also disabled the button. Clicking a disabled button in most browsers does nothing. Firefox should show NO toast because the click event doesn't fire. This is acceptable — the tooltip explains the state.

- [ ] **Step 12: Regression check — existing dashboard features**

Back in Chrome, verify that none of the following are broken:
1. Typing a command and pressing Enter → sends normally
2. Typing a command and clicking Send → sends normally
3. Destination buttons (Navigate to table_1, table_2, etc.) → all clickable, all navigate
4. Preflight checks panel → expands, runs, shows results
5. Map panel → renders, shows robot pose, click-to-navigate still works
6. Chat area → messages still stream in
7. Semantic map editor → right-click a destination button → edit dialog still works

If all 7 regression checks pass, the feature ships.

- [ ] **Step 13: No commit unless bugs found**

If all steps in this task pass, there are no changes to commit.

If any step fails, fix the root cause in `dashboard/static/index.html`, re-verify the failing step and all prior steps in this task, then commit with:

```bash
git add dashboard/static/index.html
git commit -m "fix(dashboard): <describe the specific bug fixed>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 12: Visual QA pass

Purely cosmetic verification. Non-blocking per spec Section 8.7, but worth catching before shipping.

- [ ] **Step 1: V1 — mic icon visible**

Load dashboard. Confirm the microphone SVG icon is clearly visible against the dark button background. Stroke color should be `#8899aa` at rest, `#00d4ff` on hover.

- [ ] **Step 2: V2 — recording row accent matches palette**

Click mic to enter recording state. Confirm the red tint is present but subtle — it should not clash with the cyan dashboard accent. The red dot and Cancel button's red should be consistent (`#ff4466` family).

- [ ] **Step 3: V3 — waveform smoothness**

While recording, observe the waveform. It should animate smoothly without stuttering. If the frame rate drops noticeably, check DevTools → Performance profile for blocking work.

- [ ] **Step 4: V4 — no layout shift**

Toggle between idle and recording states several times. The content below the input area (specifically the "Navigate to" destination buttons) must NOT jump. Both rows have `min-height: 38px` to prevent shift.

- [ ] **Step 5: V5 — tap target sizing**

Hover over Cancel and Stop buttons. They should be at least ~32px tall by visual inspection. Easy to click with a trackpad.

- [ ] **Step 6: V6 — toast positioning**

Trigger an error toast (e.g., by briefly going offline and clicking mic). Confirm the toast appears in the top-right area and does NOT cover the input row or the destination buttons.

- [ ] **Step 7: Final commit if any visual fixes were needed**

```bash
git add dashboard/static/index.html
git commit -m "polish(dashboard): <describe visual fix>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist (to be completed after plan execution)

After all 12 tasks pass, verify the implementation against the spec:

- [ ] Every spec decision (Q1–Q5) is reflected in behavior
- [ ] All 10 error categories from Section 7.1 have corresponding handling in the code
- [ ] All 7 race conditions from Section 7.2 are guarded
- [ ] `transitionToIdle()` is the single exit funnel for all RECORDING exit paths
- [ ] No automated tests were added (spec Section 8 is manual-only)
- [ ] `dashboard/dashboard_server.py` is unchanged
- [ ] `campus_guide_bot/` is unchanged
- [ ] All commits have conventional commit prefixes and Co-Authored-By trailer
