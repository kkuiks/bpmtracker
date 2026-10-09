/* Playback position, music and clicks advance on the same audio sample clock.
 * No requestAnimationFrame or wall-clock timer drives audible playback.
 */
class JoljakTransport extends AudioWorkletProcessor {
  constructor() {
    super();
    this.position = 0;
    this.revision = 0;
    this.playing = false;
    this.clips = [];
    this.clocks = [];
    this.referenceEvents = null;
    this.masterGain = 1;
    this.clickEnabled = false;
    this.clickGain = .7 * 10 ** (6 / 20);
    this.loop = { enabled: false, start: 0, end: 0 };
    this.end = 0;
    this.cache = new Map();
    this.requested = new Set();
    this.blocks = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type === 'project') {
        this.clips = data.clips.slice().reverse().map(clip => ({ ...clip,
          leftGain: clip.channels === 1 ? Math.cos((clip.pan + 1) * Math.PI / 4) * clip.gain : Math.min(1, 1 - clip.pan) * clip.gain,
          rightGain: clip.channels === 1 ? Math.sin((clip.pan + 1) * Math.PI / 4) * clip.gain : Math.min(1, 1 + clip.pan) * clip.gain,
        }));
        this.clocks = data.clocks.slice().reverse();
        if (data.referenceClicks) {
          const events = new Map();
          for (const time of data.referenceClicks.beats) events.set(Math.round(time * sampleRate), false);
          for (const time of data.referenceClicks.bars) events.set(Math.round(time * sampleRate), true);
          this.referenceEvents = [...events].sort((a,b)=>a[0]-b[0]).map(([frame,strong])=>({time:frame/sampleRate,strong}));
        } else this.referenceEvents = null;
        this.masterGain = data.masterGain; this.end = data.end;
      } else if (data.type === 'transport') {
        if (data.revision !== undefined && data.revision < this.revision) return;
        if (data.revision !== undefined && data.revision > this.revision) this.requested.clear();
        if (data.revision !== undefined) this.revision = data.revision;
        if (data.position !== undefined) this.position = data.position;
        if (data.playing !== undefined) this.playing = data.playing;
        if (data.loop) this.loop = data.loop;
        if (data.clickEnabled !== undefined) this.clickEnabled = data.clickEnabled;
        if (data.clickGain !== undefined) this.clickGain = data.clickGain;
        if (data.revision !== undefined) this.port.postMessage({ type: 'transport-ack', revision: this.revision, position: this.position, playing: this.playing });
      } else if (data.type === 'chunk') {
        const split = data.key.lastIndexOf(':');
        const id = data.key.slice(0, split), index = Number(data.key.slice(split + 1));
        if (!this.cache.has(id)) this.cache.set(id, new Map());
        this.cache.get(id).set(index, { samples: new Float32Array(data.buffer), used: currentFrame });
        this.requested.delete(data.key);
      } else if (data.type === 'clear') {
        this.cache.clear(); this.requested.clear();
      }
    };
  }
  sample(clip, index, channel) {
    if (index < 0 || index >= clip.frames) return 0;
    const chunkFrames = clip.sampleRate * 2;
    const chunk = Math.floor(index / chunkFrames);
    const stored = this.cache.get(clip.assetId)?.get(chunk);
    if (!stored) {
      const key = clip.assetId + ':' + chunk;
      if (!this.requested.has(key)) { this.requested.add(key); this.port.postMessage({ type: 'need', revision: this.revision, assetId: clip.assetId, index: chunk }); }
      return null;
    }
    stored.used = currentFrame;
    return stored.samples[(index - chunk * chunkFrames) * clip.channels + channel] || 0;
  }
  referencePulse(time) {
    let left=0, right=this.referenceEvents.length;
    while (left<right) {
      const middle=(left+right)>>>1;
      if (this.referenceEvents[middle].time<=time+1e-9) left=middle+1;
      else right=middle;
    }
    return left ? this.referenceEvents[left-1] : null;
  }
  process(_inputs, outputs) {
    const out = outputs[0];
    if (!out || out.length < 2) return true;
    const left = out[0], right = out[1];
    let peakLeft = 0, peakRight = 0;
    const playedTracks = new Set();
    if (this.playing) {
      for (let frame = 0; frame < left.length; frame++) {
        if (this.loop.enabled && this.loop.end > this.loop.start && this.position >= this.loop.end && this.position - 1 / sampleRate < this.loop.end) this.position = this.loop.start + (this.position - this.loop.end);
        if (this.position >= this.end) { this.playing = false; this.port.postMessage({ type: 'ended', revision: this.revision, position: this.position }); break; }
        const time = this.position;
        let l = 0, r = 0, missing = false;
        playedTracks.clear();
        for (const clip of this.clips) {
          if (!clip.audible || time < clip.start || time >= clip.start + clip.duration) continue;
          if (playedTracks.has(clip.trackId)) continue;
          playedTracks.add(clip.trackId); // Cubase: only the front event plays on an audio track.
          const sourceFrame = (time - clip.start + clip.sourceStart) * clip.sampleRate;
          const index = Math.floor(sourceFrame), fraction = sourceFrame - index;
          const a = this.sample(clip, index, 0), b = this.sample(clip, Math.min(index + 1, clip.frames - 1), 0);
          if (a === null || b === null) { missing = true; continue; }
          const first = a + (b - a) * fraction;
          if (clip.channels === 1) {
            l += first * clip.leftGain;
            r += first * clip.rightGain;
          } else {
            const c = this.sample(clip, index, 1), d = this.sample(clip, Math.min(index + 1, clip.frames - 1), 1);
            if (c === null || d === null) { missing = true; continue; }
            l += first * clip.leftGain;
            r += (c + (d - c) * fraction) * clip.rightGain;
          }
        }
        if (missing) { this.playing = false; this.port.postMessage({ type: 'buffering', revision: this.revision, position: time }); break; }
        if (this.clickEnabled) {
          if (this.referenceEvents !== null) {
            const pulse=this.referencePulse(time), age=pulse ? time-pulse.time : Infinity;
            if (age>=-1e-9 && age<.035) {
              const elapsed=Math.max(0,age), strong=pulse.strong;
              const tone=Math.sin(2*Math.PI*(strong?1600:1050)*elapsed)*Math.exp(-elapsed/.006)*(strong ? .32 : .20)*this.clickGain;
              l+=tone; r+=tone;
            }
          } else {
          // Most recently applied clock owns an overlapping scope.
          let clock = null;
          for (const candidate of this.clocks) if (time >= candidate.start && time < candidate.end) { clock = candidate; break; }
          if (clock) {
            const step = 60 / clock.bpm * 4 / clock.denominator;
            const beat = Math.floor((time - clock.phase) / step + 1e-9);
            const age = time - (clock.phase + beat * step);
            if (age >= 0 && age < .035) {
              const strong = ((beat % clock.numerator) + clock.numerator) % clock.numerator === 0;
              const tone = Math.sin(2 * Math.PI * (strong ? 1600 : 1050) * age) * Math.exp(-age / .006) * (strong ? .32 : .20) * this.clickGain;
              l += tone; r += tone;
            }
          }
          }
        }
        l *= this.masterGain; r *= this.masterGain;
        left[frame] = l; right[frame] = r;
        peakLeft = Math.max(peakLeft, Math.abs(l)); peakRight = Math.max(peakRight, Math.abs(r));
        this.position += 1 / sampleRate;
      }
    }
    if (++this.blocks % 16 === 0) this.port.postMessage({ type: 'position', revision: this.revision, position: this.position, playing: this.playing, peaks: [peakLeft, peakRight] });
    if (this.blocks % 512 === 0) for (const chunks of this.cache.values()) for (const [index, item] of chunks) if (currentFrame - item.used > sampleRate * 12) chunks.delete(index);
    return true;
  }
}
registerProcessor('joljak-transport', JoljakTransport);
