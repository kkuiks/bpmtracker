// Click boost is relative to the owner's new review default, not channel unity.
export const LEGACY_CLICK_GAIN = 0.7;
export const DEFAULT_CLICK_GAIN = LEGACY_CLICK_GAIN * 10 ** (6 / 20);
export const MAX_CLICK_BOOST_DB = 12;
export const CLICK_GAIN_POLICY = "review-plus6-v1" as const;

export function upgradedClickGain(gain: number | undefined, policy: string | undefined) {
  if (gain === undefined || policy !== CLICK_GAIN_POLICY && Math.abs(gain - LEGACY_CLICK_GAIN) < 1e-9)
    return DEFAULT_CLICK_GAIN;
  return gain;
}
