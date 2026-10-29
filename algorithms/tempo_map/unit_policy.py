"""Retain the original source family unit; no numeric tempo target or reference."""
def select_source_unit(prepared, initial):
    names=('bpm','numerator','denominator','bar_zero_source_seconds')
    matches=[u for u in prepared['units'] if any(all(abs(c[k]-initial[k])<=1e-9 for k in names) for c in u['initials'])]
    if len(matches)!=1:raise RuntimeError('Original source unit not uniquely recoverable')
    return {'available':prepared['available'],'unit_id':matches[0]['id'],'numeric_initial_used_only_to_match_existing_source_unit':True}
