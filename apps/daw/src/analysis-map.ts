/** The source-relative Tempo map. Project editing continues to use Project's map. */
export type VariableMap = {
  status: "map";
  duration_seconds: number;
  initial: { bpm: number; numerator: number; denominator: number; bar_zero_source_seconds: number };
  events: { time: number; quarter: number; bpm?: number; numerator?: number; denominator?: number }[];
  [key: string]: unknown;
};

const EPS = 1e-8;
export function isVariableMap(value: unknown): value is VariableMap {
  if (!value || typeof value !== "object") return false;
  const map = value as VariableMap;
  return map.status === "map" && !!map.initial && Array.isArray(map.events)
    && [map.duration_seconds, map.initial.bpm, map.initial.numerator,
      map.initial.denominator, map.initial.bar_zero_source_seconds].every(Number.isFinite);
}

export function validateVariableMap(map: VariableMap): void {
  const validMeter = (n: number, d: number) => Number.isInteger(n) && n >= 1 && n <= 32 && [1, 2, 4, 8, 16, 32].includes(d);
  if (map.duration_seconds <= 0 || map.initial.bpm < 1 || map.initial.bpm > 1000
      || !validMeter(map.initial.numerator, map.initial.denominator)) throw new Error("Invalid analyzed tempo map.");
  let time = map.initial.bar_zero_source_seconds, quarter = 0, bpm = map.initial.bpm;
  let n = map.initial.numerator, d = map.initial.denominator, barQuarter = 0, previous = 0;
  for (const event of map.events) {
    const expected = time + (event.quarter - quarter) * 60 / bpm;
    const beat = (event.quarter - barQuarter) * d / 4;
    if (![event.time, event.quarter].every(Number.isFinite) || event.time <= previous + EPS
        || event.time >= map.duration_seconds || Math.abs(expected - event.time) > 1e-7
        || Math.abs(beat - Math.round(beat)) > 1e-7) throw new Error("The analyzed map has an invalid change boundary.");
    if (event.bpm !== undefined && (!Number.isFinite(event.bpm) || event.bpm < 1 || event.bpm > 1000))
      throw new Error("Invalid analyzed tempo.");
    if ((event.numerator === undefined) !== (event.denominator === undefined)
        || event.numerator !== undefined && !validMeter(event.numerator, event.denominator!))
      throw new Error("Invalid analyzed signature.");
    time = event.time; quarter = event.quarter; bpm = event.bpm ?? bpm; previous = time;
    if (event.numerator !== undefined) { n = event.numerator; d = event.denominator!; barQuarter = quarter; }
  }
}

export function sourceMapState(map: VariableMap, seconds: number) {
  let time = map.initial.bar_zero_source_seconds, quarter = 0, bpm = map.initial.bpm;
  let numerator = map.initial.numerator, denominator = map.initial.denominator, barQuarter = 0;
  for (const event of map.events) {
    if (event.time > seconds + EPS) break;
    time = event.time; quarter = event.quarter; bpm = event.bpm ?? bpm;
    if (event.numerator !== undefined) { numerator = event.numerator; denominator = event.denominator!; barQuarter = quarter; }
  }
  const at = quarter + (seconds - time) * bpm / 60;
  const barLength = numerator * 4 / denominator;
  const barStart = barQuarter + Math.floor((at - barQuarter + EPS) / barLength) * barLength;
  return { bpm, numerator, denominator, quarter: at, barStart, phase: seconds - (at - barStart) * 60 / bpm };
}

export function sourceMapTime(map: VariableMap, targetQuarter: number): number {
  let time = map.initial.bar_zero_source_seconds, quarter = 0, bpm = map.initial.bpm;
  for (const event of map.events) {
    if (event.quarter > targetQuarter + EPS) break;
    time = event.time; quarter = event.quarter; bpm = event.bpm ?? bpm;
  }
  return time + (targetQuarter - quarter) * 60 / bpm;
}

export function sourceMapSections(map: VariableMap) {
  const boundaries = [0, ...map.events.map(event => event.time), map.duration_seconds];
  return boundaries.slice(0, -1).map((start, index) => ({ ...sourceMapState(map, start), start, end: boundaries[index + 1] }));
}

export function firstMapDownbeat(map: VariableMap, from: number, to: number): number | null {
  for (const section of sourceMapSections(map)) {
    const start = Math.max(from, section.start), end = Math.min(to, section.end);
    if (end <= start) continue;
    const period = 60 / section.bpm * section.numerator * 4 / section.denominator;
    const tick = section.phase + Math.ceil((start - section.phase - EPS) / period) * period;
    if (tick < end - EPS) return tick;
  }
  return null;
}

export function isMapDownbeat(map: VariableMap, seconds: number): boolean {
  const state = sourceMapState(map, seconds);
  return Math.abs(state.quarter - state.barStart) < 1e-7;
}
