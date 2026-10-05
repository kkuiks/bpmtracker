"""Retain a numerical timeline when notation cannot be exported."""
from .timeline import decode
from .legacy_export import export_map


CLOCK_FAILURES = {
    'insufficient quarter observations',
    'no positive quarter clock',
    'nonmonotonic continuous clock',
}
NOTATION_FAILURES = {'no resolved meter proposal', 'unresolved first bar'}


def analyse(fields, source):
    """Expected inference failures remain failures, with useful stages saved.

    Unexpected errors propagate. No constant-meter or legacy-engine fallback
    manufactures a complete map. Retained physical output is an estimate.
    """
    try:
        timeline = decode(fields, source)
    except ValueError as exc:
        if str(exc) not in CLOCK_FAILURES:
            raise
        return dict(status='decode_failed', stage='clock', error=str(exc),
                    map=None, physical_timeline=None, fallback_used=False,
                    reference_read=False, source_only=True)
    try:
        musical_map, export = export_map(timeline)
    except ValueError as exc:
        if str(exc) not in NOTATION_FAILURES:
            raise
        return dict(status='decode_failed', stage='notation', error=str(exc),
                    map=None, physical_timeline=timeline, fallback_used=False,
                    reference_read=False, source_only=True)
    return dict(status='rendered', map=musical_map, physical_timeline=timeline,
                export=export, fallback_used=False, reference_read=False,
                source_only=True)
