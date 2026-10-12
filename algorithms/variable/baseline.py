"""Explicit L2 entry point, reusing the unchanged measured implementation.

This module selects the owner's new development standard. It introduces no new
search parameters or scoring rules, and does not switch the DAW Analyze command.
Prepare audio observations/candidates first; the caller then supplies only the
discrete initial-unit packet. Evaluation references never enter this API.
"""
from experiments.beat_event_map_v1.source import prepare as _prepare
from experiments.beat_event_stability_v1.core import fit as _fit

METHOD = "L2_DENSE_PROPOSALS"


def prepare_source(events, family=None):
    """Prepare candidates from source-only observations before reading a tap."""
    return _prepare(events, family)


def predict(events, prepared_source, initial_unit, progress=None):
    """Fit the current baseline from previously prepared source candidates.

    initial_unit is the existing available/unit_id packet, not a numeric tap.
    Discard additional packet metadata before fitting. The returned map retains
    the frozen implementation's fields; caller/run provenance stays separate.
    """
    packet = {"available": initial_unit.get("available", False),
              "unit_id": initial_unit.get("unit_id")}
    return _fit(events, prepared_source, packet, METHOD, progress=progress)
