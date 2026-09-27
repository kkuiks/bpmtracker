"""Explicit musical units for research fixtures and future map contracts.

These value objects convert declared units only. They do not infer musical
meter, assign grouping from a time signature, or decide map equivalence.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Integral, Real


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return int(value)


def _finite_real(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite real number')
    return float(value)


@dataclass(frozen=True)
class TempoSpec:
    """A BPM value whose counted duration is explicit in quarter-note units.

    For example, 80 BPM counting dotted quarters is 120 quarter notes/minute.
    A unit is mandatory: an unresolved acoustic pulse rate is not quarter BPM.
    """
    bpm: float
    unit_quarters: Fraction

    def __post_init__(self):
        bpm = _finite_real(self.bpm, 'bpm')
        if bpm <= 0:
            raise ValueError('bpm must be positive')
        if (isinstance(self.unit_quarters, bool) or
                not isinstance(self.unit_quarters, (Fraction, Integral)) or
                self.unit_quarters <= 0):
            raise ValueError('unit_quarters must be an explicit positive Fraction or integer')
        unit = Fraction(self.unit_quarters)
        quarter_bpm = bpm * float(unit)
        if not math.isfinite(quarter_bpm) or quarter_bpm <= 0:
            raise ValueError('converted quarter BPM must be finite and positive')
        object.__setattr__(self, 'bpm', bpm)
        object.__setattr__(self, 'unit_quarters', unit)

    @property
    def quarter_bpm(self):
        return self.bpm * float(self.unit_quarters)

    def seconds_for_quarters(self, quarters):
        """Convert a signed musical duration; negative pickup context is valid."""
        quarters = _finite_real(quarters, 'quarters')
        seconds = quarters / self.quarter_bpm * 60.0
        if not math.isfinite(seconds):
            raise ValueError('converted duration must be finite')
        return seconds

    def to_dict(self):
        return {'bpm': self.bpm,
                'bpm_unit_quarters': {'numerator': self.unit_quarters.numerator,
                                      'denominator': self.unit_quarters.denominator},
                'quarter_bpm': self.quarter_bpm}


@dataclass(frozen=True)
class MeterSpec:
    """A signature and optional explicitly asserted denominator-unit grouping.

    No grouping is inferred, including for 4/4, 6/8, or 5/8. Conventional binary
    note-value denominators are supported by this initial research primitive;
    other notational systems require an explicit extension.
    """
    numerator: int
    denominator: int
    grouping: tuple[int, ...] | None = None

    def __post_init__(self):
        numerator = _positive_integer(self.numerator, 'numerator')
        denominator = _positive_integer(self.denominator, 'denominator')
        if denominator & (denominator - 1):
            raise ValueError('denominator must be a power of two')
        grouping = self.grouping
        if grouping is not None:
            if not isinstance(grouping, (tuple, list)) or not grouping:
                raise ValueError('grouping must be a nonempty list or tuple, or None')
            grouping = tuple(_positive_integer(v, 'group size') for v in grouping)
            if sum(grouping) != numerator:
                raise ValueError('grouping must sum to the meter numerator')
        object.__setattr__(self, 'numerator', numerator)
        object.__setattr__(self, 'denominator', denominator)
        object.__setattr__(self, 'grouping', grouping)

    @property
    def quarters_per_notated_unit(self):
        return Fraction(4, self.denominator)

    @property
    def quarters_per_bar(self):
        return self.numerator * self.quarters_per_notated_unit

    @property
    def group_offsets_quarters(self):
        if self.grouping is None:
            return None
        offsets = []
        position = Fraction(0)
        for size in self.grouping:
            offsets.append(position)
            position += size * self.quarters_per_notated_unit
        return tuple(offsets)

    def bar_seconds(self, tempo):
        if not isinstance(tempo, TempoSpec):
            raise TypeError('tempo must declare a TempoSpec')
        return tempo.seconds_for_quarters(self.quarters_per_bar)

    def group_durations_seconds(self, tempo):
        if not isinstance(tempo, TempoSpec):
            raise TypeError('tempo must declare a TempoSpec')
        if self.grouping is None:
            return None
        return tuple(tempo.seconds_for_quarters(n * self.quarters_per_notated_unit)
                     for n in self.grouping)

    def to_dict(self):
        duration = self.quarters_per_bar
        return {'numerator': self.numerator, 'denominator': self.denominator,
                'grouping_denominator_units': list(self.grouping) if self.grouping is not None else None,
                'quarters_per_bar': {'numerator': duration.numerator, 'denominator': duration.denominator}}
