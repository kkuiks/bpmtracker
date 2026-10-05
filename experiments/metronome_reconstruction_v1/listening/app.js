"use strict";

const $ = (id) => document.getElementById(id);
const ui = Object.fromEntries([
  "track-list", "track-title", "selected-rank", "bpm", "meter", "quarter-error", "bar-error", "track-note",
  "map-download", "seek", "current-time", "duration", "play", "status", "loop", "support-note", "offset-note",
  "click-enabled", "accent-enabled", "music-volume", "click-volume", "timeline",
].map(id => [id, $(id)]));
const state = {
  data: null, track: null, context: null, music: null, clicks: null,
  musicGain: null, clickGain: null, musicSource: null, clickSource: null,
  position: 0, startedAt: 0, startPosition: 0, playing: false,
  mode: "predicted", loading: false, generation: 0, controller: null,
  looping: false, loopStart: 0, loopEnd: 0, timelineStart: 0, timelineSpan: 9, draggingSeek: false,
};

function formatTime(seconds, decimal = false) {
  const value = Math.max(0, seconds);
  let tenths = Math.floor(value * 10 + 1e-6);
  const minutes = Math.floor(tenths / 600);
  const whole = Math.floor(tenths / 10) % 60;
  return `${minutes}:${String(whole).padStart(2, "0")}${decimal ? `.${tenths % 10}` : ""}`;
}

function duration() {
  return state.music ? state.music.duration : state.track?.duration_seconds || 0;
}

function position() {
  if (!state.playing) return state.position;
  const elapsed = Math.max(0, state.context.currentTime - state.startedAt);
  const raw = state.startPosition + elapsed;
  if (state.looping && raw >= state.loopEnd) {
    return state.loopStart + ((raw - state.loopStart) % (state.loopEnd - state.loopStart));
  }
  return Math.min(raw, duration());
}

function stopSources() {
  for (const source of [state.musicSource, state.clickSource]) {
    if (!source) continue;
    source.onended = null;
    try { source.stop(); } catch (_) { /* A stopped source is already detached. */ }
    source.disconnect();
  }
  state.musicSource = state.clickSource = null;
}

function pause() {
  state.position = position();
  state.playing = false;
  stopSources();
  updateTransport();
}

function ensureContext() {
  if (state.context) return state.context;
  const Constructor = window.AudioContext || window.webkitAudioContext;
  if (!Constructor) throw new Error("이 브라우저에서는 오디오 재생을 지원하지 않습니다.");
  state.context = new Constructor();
  state.musicGain = state.context.createGain();
  state.clickGain = state.context.createGain();
  state.musicGain.connect(state.context.destination);
  state.clickGain.connect(state.context.destination);
  setVolumes();
  return state.context;
}

function setVolumes() {
  $("music-volume-value").textContent = `${ui["music-volume"].value}%`;
  $("click-volume-value").textContent = `${ui["click-volume"].value}%`;
  if (!state.context) return;
  state.musicGain.gain.setTargetAtTime(Number(ui["music-volume"].value) / 100, state.context.currentTime, .012);
  state.clickGain.gain.setTargetAtTime(ui["click-enabled"].checked ? Number(ui["click-volume"].value) / 100 : 0, state.context.currentTime, .012);
}

function renderClicks() {
  if (!state.music) return;
  // Audio and click buffers share the same sample clock and zero. These event
  // times are copied from the saved maps; no BPM/phase is fitted in the player.
  const rate = state.context.sampleRate;
  const buffer = state.context.createBuffer(1, state.music.length, rate);
  const samples = buffer.getChannelData(0);
  const events = state.track[state.mode];
  const accents = ui["accent-enabled"].checked;
  const downbeatFrames = new Set(events.downbeat.map(time => Math.round(time * rate)));
  const tone = (time, accented) => {
    const start = Math.round(time * rate);
    const length = Math.round(rate * (accented ? .014 : .009));
    const frequency = accented ? 2050 : 1300;
    const amplitude = accented ? .8 : .48;
    for (let frame = 0; frame < length; frame++) {
      const target = start + frame;
      if (target < 0 || target >= samples.length) continue;
      const t = frame / rate;
      const envelope = Math.min(1, frame / Math.max(1, rate * .0005)) * Math.exp(-t / (accented ? .0032 : .0023));
      samples[target] += amplitude * envelope * Math.sin(2 * Math.PI * frequency * t);
    }
  };
  for (const time of events.quarter) {
    if (!(accents && downbeatFrames.has(Math.round(time * rate)))) tone(time, false);
  }
  if (accents) for (const time of events.downbeat) tone(time, true);
  state.clicks = buffer;
}

function startPlayback() {
  if (!state.music || !state.clicks) return;
  stopSources();
  const length = duration();
  if (state.position >= length - .001) state.position = state.looping ? state.loopStart : 0;
  const when = state.context.currentTime + .06;
  const music = state.context.createBufferSource();
  const clicks = state.context.createBufferSource();
  music.buffer = state.music;
  clicks.buffer = state.clicks;
  for (const source of [music, clicks]) {
    source.loop = state.looping;
    source.loopStart = state.loopStart;
    source.loopEnd = state.loopEnd;
  }
  music.connect(state.musicGain);
  clicks.connect(state.clickGain);
  state.musicSource = music;
  state.clickSource = clicks;
  state.startPosition = state.position;
  state.startedAt = when;
  state.playing = true;
  music.onended = () => {
    if (state.musicSource !== music) return;
    state.position = duration();
    state.playing = false;
    stopSources();
    updateTransport();
  };
  music.start(when, state.position);
  clicks.start(when, state.position);
  updateTransport();
}

function reconfigureClicks() {
  const resume = state.playing;
  pause();
  state.clicks = null;
  renderClicks();
  if (resume) startPlayback();
  updateStatus();
}

async function loadAudio() {
  const generation = state.generation;
  const track = state.track;
  const context = ensureContext();
  // Called from the play-button gesture, before waiting on the fetch.
  await context.resume();
  if (generation !== state.generation) return false;
  state.loading = true;
  state.controller = new AbortController();
  updateTransport();
  ui.status.textContent = `원음 불러오는 중 · ${(track.audio_bytes / 1e6).toFixed(1)} MB`;
  try {
    const response = await fetch(track.audio_url, {signal: state.controller.signal});
    if (!response.ok) throw new Error(`음원을 불러오지 못했습니다 (${response.status}).`);
    const bytes = await response.arrayBuffer();
    if (generation !== state.generation) return false;
    ui.status.textContent = "음원 재생 준비 중…";
    const music = await context.decodeAudioData(bytes);
    if (generation !== state.generation) return false;
    state.music = music;
    state.loopEnd = Math.min(state.loopEnd, duration());
    ui.seek.max = duration();
    renderClicks();
    return true;
  } catch (error) {
    if (generation !== state.generation || error.name === "AbortError") return false;
    ui.status.textContent = `${error.message || "음원 재생 준비에 실패했습니다."} 곡을 다시 선택해 주세요.`;
    return false;
  } finally {
    if (generation === state.generation) {
      state.loading = false;
      state.controller = null;
      updateTransport();
    }
  }
}

async function togglePlay() {
  if (state.loading || !state.track) return;
  if (state.playing) { pause(); updateStatus(); return; }
  const generation = state.generation;
  try {
    if (!state.music && !(await loadAudio())) return;
    await ensureContext().resume();
    if (generation !== state.generation) return;
    if (state.context.state !== "running") throw new Error("브라우저의 오디오 재생을 허용해 주세요.");
    startPlayback();
    updateStatus();
  } catch (error) {
    pause();
    ui.status.textContent = error.message;
  }
}

function setLoop(enabled) {
  state.looping = enabled;
  ui.loop.setAttribute("aria-pressed", String(enabled));
}

function seek(time) {
  if (!state.track) return;
  const resume = state.playing;
  pause();
  state.position = Math.max(0, Math.min(time, duration()));
  if (state.looping && (state.position < state.loopStart || state.position >= state.loopEnd)) setLoop(false);
  if (resume) startPlayback();
  updateStatus();
}

function toggleLoop() {
  if (!state.track) return;
  const resume = state.playing;
  pause();
  if (state.looping) {
    setLoop(false);
  } else {
    state.loopStart = Math.max(0, Math.min(state.position, duration() - 12));
    state.loopEnd = Math.min(duration(), state.loopStart + 12);
    state.position = state.loopStart;
    setLoop(true);
  }
  if (resume) startPlayback();
  updateStatus();
}

function updateTransport() {
  ui.play.disabled = !state.track || state.loading;
  ui.play.textContent = state.loading ? "불러오는 중…" : state.playing ? "일시정지" : state.music ? "재생" : "불러와 재생";
}

function inReferenceSupport(time) {
  return state.track.reference_support_seconds.some(([start, end]) => time >= start && time <= end);
}

function updateStatus() {
  if (state.loading || !state.track) return;
  if (!state.music) { ui.status.textContent = "재생을 누르면 원음을 불러옵니다."; return; }
  const mode = ui["click-enabled"].checked ? (state.mode === "predicted" ? "예측 클릭" : "참조 클릭") : "원음만";
  const loop = state.looping ? ` · ${formatTime(state.loopStart)}–${formatTime(state.loopEnd)} 반복` : "";
  const noReference = state.mode === "reference" && !inReferenceSupport(position()) ? " · 참조가 없는 구간" : "";
  ui.status.textContent = `${state.playing ? "재생 중" : "일시정지"} · ${mode}${loop}${noReference}`;
}

function selectTrack(index) {
  pause();
  state.controller?.abort();
  state.generation++;
  state.loading = false;
  state.controller = null;
  // Only the currently selected recording is kept decoded in memory.
  state.music = state.clicks = null;
  state.position = 0;
  state.track = state.data.tracks[index];
  setLoop(false);
  const track = state.track;
  document.querySelectorAll(".track-card").forEach((button, i) => button.setAttribute("aria-pressed", String(index === i)));
  ui["track-title"].textContent = track.title;
  ui["selected-rank"].textContent = `${String(track.rank).padStart(2, "0")} / ${String(state.data.count).padStart(2, "0")}`;
  ui.bpm.textContent = String(track.quarter_bpm);
  ui.meter.textContent = `${track.time_signature.numerator}/${track.time_signature.denominator}`;
  for (const [id, value] of [["quarter-error", track.quarter_max_error_ms], ["bar-error", track.bar_max_error_ms]]) {
    const unit = document.createElement("small");
    unit.textContent = "ms";
    ui[id].replaceChildren(document.createTextNode(value.toFixed(2)), unit);
  }
  if (track.bar_max_error_ms > track.quarter_max_error_ms + 50) {
    ui["track-note"].textContent = "박 위치에 비해 마디 첫 박의 위치 차이가 큽니다. ‘마디 첫 박 강조’를 켠 상태로 예측과 참조를 바꿔 들어보세요.";
  } else {
    const sign = track.quarter_initial_error_ms < 0 ? "앞서" : "뒤에";
    ui["track-note"].textContent = `시작의 예측 박은 참조보다 약 ${Math.abs(track.quarter_initial_error_ms).toFixed(2)}ms ${sign} 있습니다. 시작·중간·끝부분에서 차이가 누적되는지 들어보세요.`;
  }
  ui["map-download"].href = track.map_url;
  ui["map-download"].download = `${track.id}.tempo-map.json`;
  ui["map-download"].hidden = false;
  ui.seek.max = track.duration_seconds;
  ui.seek.value = 0;
  const support = track.reference_support_seconds;
  const supportEnd = Math.max(...support.map(item => item[1]));
  const hasMargin = supportEnd < track.duration_seconds - .01 || support[0][0] > .01 || support.length > 1;
  ui["support-note"].textContent = hasMargin
    ? `참조가 있는 구간: ${support.map(([a, b]) => `${formatTime(a, true)}–${formatTime(b, true)}`).join(", ")}. 그 밖에서는 참조 클릭이 없고 예측 클릭만 이어집니다.`
    : "기존 승인 참조는 입력 음원 전체 구간을 대상으로 합니다.";
  ui["offset-note"].textContent = `저장된 오프셋: ${track.offset_seconds.toFixed(6)}초 · 음원 시작을 0초로 둔 기준 마디 첫 박의 위치입니다.`;
  $("jump-reference-end").hidden = !hasMargin;
  updateTransport();
  updateStatus();
}

function makeTrackList() {
  for (const [index, track] of state.data.tracks.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "track-card";
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = String(track.rank).padStart(2, "0");
    const content = document.createElement("span");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = track.title;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${track.quarter_bpm} BPM · ${track.time_signature.numerator}/${track.time_signature.denominator} · ${formatTime(track.duration_seconds)}`;
    const error = document.createElement("span");
    error.className = "error";
    error.textContent = `최대 정렬 오차 ${track.ranking_error_ms.toFixed(2)} ms`;
    content.append(name, meta, error);
    button.append(rank, content);
    button.addEventListener("click", () => selectTrack(index));
    ui["track-list"].append(button);
  }
}

function drawTimeline(time) {
  const canvas = ui.timeline;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  if (!state.track) return;
  const left = 45, right = width - 12, scale = (right - left) / state.timelineSpan;
  const start = Math.max(0, Math.min(time - 1, Math.max(0, duration() - state.timelineSpan)));
  state.timelineStart = start;
  const x = seconds => left + (seconds - start) * scale;
  context.font = "10px system-ui,sans-serif";
  context.fillStyle = "#8295aa";
  const tick = width < 480 ? 2 : 1;
  for (let second = Math.ceil(start / tick) * tick; second <= start + state.timelineSpan; second += tick) {
    context.strokeStyle = "#233142";
    context.beginPath(); context.moveTo(x(second), 20); context.lineTo(x(second), 157); context.stroke();
    context.fillText(formatTime(second), x(second) - 10, 173);
  }
  context.fillText("원음", 9, 50);
  if (state.music) {
    const samples = state.music.getChannelData(0);
    const rate = state.music.sampleRate;
    context.strokeStyle = "#4b667b";
    context.lineWidth = 1;
    context.beginPath();
    for (let pixel = left; pixel < right; pixel += 2) {
      const a = Math.max(0, Math.floor((start + (pixel - left) / scale) * rate));
      const b = Math.min(samples.length, Math.ceil((start + (pixel + 2 - left) / scale) * rate));
      let maximum = 0;
      for (let i = a; i < b; i += 5) maximum = Math.max(maximum, Math.abs(samples[i]));
      const amplitude = Math.min(1, maximum) * 23;
      context.moveTo(pixel, 47 - amplitude); context.lineTo(pixel, 47 + amplitude);
    }
    context.stroke();
  } else {
    context.fillText("재생을 누르면 원음 파형이 표시됩니다", left + 13, 50);
  }
  for (const [name, y, color, label] of [["predicted", 96, "#7de2bb", "예측"], ["reference", 136, "#83b6ff", "참조"]]) {
    context.globalAlpha = state.mode === name && ui["click-enabled"].checked ? 1 : .55;
    context.fillStyle = color;
    context.fillText(label, 9, y + 3);
    context.strokeStyle = color;
    const marks = (events, halfHeight, lineWidth) => {
      context.lineWidth = lineWidth;
      context.beginPath();
      for (const event of events) {
        if (event < start || event > start + state.timelineSpan) continue;
        context.moveTo(x(event), y - halfHeight); context.lineTo(x(event), y + halfHeight);
      }
      context.stroke();
    };
    marks(state.track[name].quarter, 5, 1);
    marks(state.track[name].downbeat, 13, 2.5);
  }
  context.globalAlpha = 1;
  if (state.looping) {
    context.fillStyle = "#7de2bb15";
    const a = Math.max(left, x(state.loopStart)), b = Math.min(right, x(state.loopEnd));
    if (b > a) context.fillRect(a, 20, b - a, 138);
  }
  context.strokeStyle = "#f5f8fb";
  context.lineWidth = 1.5;
  context.beginPath(); context.moveTo(x(time), 17); context.lineTo(x(time), 158); context.stroke();
}

let lastStatusUpdate = 0;
function animationFrame(now) {
  const time = position();
  ui["current-time"].textContent = formatTime(time, true);
  ui.duration.textContent = formatTime(duration(), true);
  if (!state.draggingSeek) ui.seek.value = time;
  drawTimeline(time);
  if (state.playing && now - lastStatusUpdate > 250) {
    updateStatus();
    lastStatusUpdate = now;
  }
  requestAnimationFrame(animationFrame);
}

ui.play.addEventListener("click", togglePlay);
ui.seek.addEventListener("pointerdown", () => { state.draggingSeek = true; });
window.addEventListener("pointerup", () => { state.draggingSeek = false; });
window.addEventListener("pointercancel", () => { state.draggingSeek = false; });
ui.seek.addEventListener("blur", () => { state.draggingSeek = false; });
ui.seek.addEventListener("input", () => seek(Number(ui.seek.value)));
$("back").addEventListener("click", () => seek(position() - 10));
$("forward").addEventListener("click", () => seek(position() + 10));
ui.loop.addEventListener("click", toggleLoop);
$("jump-start").addEventListener("click", () => seek(0));
$("jump-middle").addEventListener("click", () => seek(duration() / 2));
$("jump-end").addEventListener("click", () => seek(duration() - 20));
$("jump-reference-end").addEventListener("click", () => seek(Math.max(...state.track.reference_support_seconds.map(item => item[1])) - 15));
for (const radio of document.querySelectorAll("input[name=clock-mode]")) {
  radio.addEventListener("change", () => { state.mode = radio.value; reconfigureClicks(); });
}
ui["accent-enabled"].addEventListener("change", reconfigureClicks);
for (const id of ["music-volume", "click-volume", "click-enabled"]) {
  ui[id].addEventListener("input", () => { setVolumes(); updateStatus(); });
}
ui.timeline.addEventListener("click", event => {
  const rectangle = ui.timeline.getBoundingClientRect();
  const fraction = (event.clientX - rectangle.left - 45) / (rectangle.width - 57);
  seek(state.timelineStart + Math.max(0, Math.min(1, fraction)) * state.timelineSpan);
});
document.addEventListener("keydown", event => {
  if (event.target.matches("button, input, a, textarea, select") || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.code === "Space") { event.preventDefault(); togglePlay(); }
  if (event.code === "ArrowLeft") { event.preventDefault(); seek(position() - 5); }
  if (event.code === "ArrowRight") { event.preventDefault(); seek(position() + 5); }
});
window.addEventListener("pagehide", () => { pause(); state.controller?.abort(); });

async function initialize() {
  try {
    const response = await fetch("index-data.json");
    if (!response.ok) throw new Error(`결과를 불러오지 못했습니다 (${response.status}).`);
    state.data = await response.json();
    if (!state.data.tracks.length) throw new Error("청취할 결과가 없습니다.");
    $("collection-count").textContent = `${state.data.count}곡 / 전체 ${state.data.full_result_denominator}곡`;
    $("run-label").textContent = state.data.run;
    $("experiment-note").textContent = state.data.reference_derived_hint_is_diagnostic_only
      ? "이번 실험은 기존 참조 BPM으로 올바른 박 단위를 제공한 진단입니다. 실제 사용자 탭이나 완전 자동 조건의 성능과 구분해 읽어주세요."
      : "저장된 실험 결과를 청취합니다. 정렬 오차는 기존 승인 참조와 비교한 수치입니다.";
    makeTrackList();
    selectTrack(0);
    requestAnimationFrame(animationFrame);
  } catch (error) {
    ui["track-title"].textContent = "페이지를 준비하지 못했습니다";
    ui.status.textContent = error.message;
  }
}

initialize();
