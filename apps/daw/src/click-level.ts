// Keep the stored 0 dB reference stable; synthesis applies output calibration.
export const LEGACY_CLICK_GAIN = 0.7;
export const DEFAULT_CLICK_GAIN = LEGACY_CLICK_GAIN * 10 ** (6 / 20);
export const MAX_CLICK_BOOST_DB = 12;
export const CLICK_GAIN_POLICY = "click-reference-v1" as const;

export function upgradedClickGain(gain: number | undefined, policy: string | undefined) {
  const current = policy === CLICK_GAIN_POLICY || typeof policy === "string" && policy.endsWith("-plus6-v1");
  if (gain === undefined || !current && Math.abs(gain - LEGACY_CLICK_GAIN) < 1e-9)
    return DEFAULT_CLICK_GAIN;
  return gain;
}
