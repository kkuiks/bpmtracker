"""Frozen comparison port of the project's historical NumPy DBN decoder.

Source SHA256: 7246a1c9b129973201e6384514170ebbacc4992977b150782a30f3986b0c4480
The implementation below this header is byte-identical to the preserved source.
Experimental comparison only: chooses one whole-song meter and discretizes beat
periods in integer activation frames. Do not interpret its output as ground truth.
"""

import math
import warnings
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np


def _as_1d_array(x, dtype=float):
    arr = np.asarray(x, dtype=dtype).reshape(-1)
    return arr


def _as_numpy_1d(x):
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-x))


def threshold_activations(activations: np.ndarray, threshold: float):
    """
    Trim leading/trailing frames whose activations are below threshold.
    Returns (trimmed_activations, first_frame_index).
    """
    arr = np.asarray(activations, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"Expected activations with shape (T, C), got {arr.shape}")
    if arr.size == 0:
        return np.empty((0, arr.shape[1]), dtype=np.float64), 0

    idx = np.flatnonzero(np.max(arr, axis=1) >= float(threshold))
    if idx.size == 0:
        return np.empty((0, arr.shape[1]), dtype=np.float64), 0
    first = int(idx[0])
    last = int(idx[-1]) + 1
    return arr[first:last], first


def exponential_transition(
    from_intervals: np.ndarray,
    to_intervals: np.ndarray,
    transition_lambda: Optional[float],
    threshold: float = np.spacing(1),
    norm: bool = True,
):
    """
    Exponential tempo transition probability matrix.
    Rows correspond to origin intervals, columns to destination intervals.
    """
    from_intervals = np.asarray(from_intervals, dtype=np.float64).reshape(-1)
    to_intervals = np.asarray(to_intervals, dtype=np.float64).reshape(-1)
    if from_intervals.size == 0 or to_intervals.size == 0:
        return np.empty((from_intervals.size, to_intervals.size), dtype=np.float64)

    if transition_lambda is None:
        out = np.zeros((from_intervals.size, to_intervals.size), dtype=np.float64)
        for i, interval in enumerate(from_intervals):
            j = int(np.argmin(np.abs(to_intervals - interval)))
            out[i, j] = 1.0
        return out

    ratio = to_intervals[None, :] / from_intervals[:, None]
    prob = np.exp(-float(transition_lambda) * np.abs(ratio - 1.0))
    prob[prob <= float(threshold)] = 0.0
    if not norm:
        return prob

    row_sum = np.sum(prob, axis=1, keepdims=True)
    zero_rows = np.flatnonzero(row_sum.reshape(-1) <= 0.0)
    for i in zero_rows:
        j = int(np.argmin(np.abs(to_intervals - from_intervals[i])))
        prob[i, j] = 1.0
    row_sum = np.sum(prob, axis=1, keepdims=True)
    prob /= row_sum
    return prob


class BeatStateSpace:
    def __init__(self, min_interval: float, max_interval: float, num_intervals: Optional[int] = None):
        intervals = np.arange(np.round(min_interval), np.round(max_interval) + 1)
        if num_intervals is not None and num_intervals < len(intervals):
            num_log_intervals = int(num_intervals)
            intervals = []
            while len(intervals) < int(num_intervals):
                intervals = np.logspace(
                    np.log2(min_interval),
                    np.log2(max_interval),
                    num_log_intervals,
                    base=2,
                )
                intervals = np.unique(np.round(intervals))
                num_log_intervals += 1

        self.intervals = np.ascontiguousarray(intervals, dtype=int)
        self.num_states = int(np.sum(self.intervals))
        self.num_intervals = int(len(self.intervals))

        first_states = np.cumsum(np.r_[0, self.intervals[:-1]])
        self.first_states = first_states.astype(int)
        self.last_states = np.cumsum(self.intervals) - 1

        self.state_positions = np.empty(self.num_states, dtype=np.float64)
        self.state_intervals = np.empty(self.num_states, dtype=int)
        idx = 0
        for interval in self.intervals:
            self.state_positions[idx : idx + interval] = np.linspace(0, 1, interval, endpoint=False)
            self.state_intervals[idx : idx + interval] = interval
            idx += interval


class BarStateSpace:
    def __init__(
        self,
        num_beats: int,
        min_interval: float,
        max_interval: float,
        num_intervals: Optional[int] = None,
    ):
        self.num_beats = int(num_beats)
        self.state_positions = np.empty(0, dtype=np.float64)
        self.state_intervals = np.empty(0, dtype=int)
        self.num_states = 0
        self.first_states = []
        self.last_states = []

        bss = BeatStateSpace(min_interval, max_interval, num_intervals)
        for _ in range(self.num_beats):
            self.state_positions = np.hstack((self.state_positions, bss.state_positions + len(self.first_states)))
            self.state_intervals = np.hstack((self.state_intervals, bss.state_intervals))
            self.first_states.append((bss.first_states + self.num_states).astype(int))
            self.last_states.append((bss.last_states + self.num_states).astype(int))
            self.num_states += bss.num_states


@dataclass
class _BoundaryGroup:
    dest_states: np.ndarray
    prev_states: np.ndarray
    log_transition: np.ndarray


class _BarHMMFast:
    """
    Viterbi decoder specialized for the bar-transition topology used by madmom
    downbeat DBN (constant-tempo transitions inside beats + boundary tempo jumps).
    """

    def __init__(
        self,
        state_space: BarStateSpace,
        transition_lambda: Sequence[Optional[float]],
        observation_lambda: int,
    ):
        if len(transition_lambda) != state_space.num_beats:
            raise ValueError("transition_lambda length must match num_beats")

        self.state_space = state_space
        self.num_states = int(state_space.num_states)
        self.observation_lambda = int(observation_lambda)

        border = 1.0 / float(self.observation_lambda)
        pointers = np.zeros(self.num_states, dtype=np.uint32)
        pointers[state_space.state_positions % 1 < border] = 1
        pointers[state_space.state_positions < border] = 2
        self.om_pointers = pointers

        first_flat = np.unique(np.concatenate([np.asarray(x, dtype=int) for x in state_space.first_states]))
        keep = np.ones(self.num_states, dtype=bool)
        keep[first_flat] = False
        det_dest = np.flatnonzero(keep).astype(np.int32)
        self.det_dest = det_dest
        self.det_prev = (det_dest - 1).astype(np.int32)

        boundary_groups = []
        for beat_idx in range(state_space.num_beats):
            dest_states = np.asarray(state_space.first_states[beat_idx], dtype=np.int32)
            prev_states = np.asarray(state_space.last_states[beat_idx - 1], dtype=np.int32)
            from_int = state_space.state_intervals[prev_states]
            to_int = state_space.state_intervals[dest_states]
            prob = exponential_transition(from_int, to_int, transition_lambda[beat_idx])
            with np.errstate(divide="ignore"):
                log_prob = np.log(prob.astype(np.float64))
            boundary_groups.append(
                _BoundaryGroup(
                    dest_states=dest_states,
                    prev_states=prev_states,
                    log_transition=log_prob,
                )
            )
        self.boundary_groups = boundary_groups

        self.initial_log_distribution = np.log(np.ones(self.num_states, dtype=np.float64) / float(self.num_states))

    def _log_densities(self, activations: np.ndarray):
        eps = np.finfo(np.float64).tiny
        activations = np.asarray(activations, dtype=np.float64)
        if activations.ndim != 2 or activations.shape[1] != 2:
            raise ValueError(f"Expected activations shape (T, 2), got {activations.shape}")

        beat = np.clip(activations[:, 0], eps, 1.0)
        downbeat = np.clip(activations[:, 1], eps, 1.0)
        no_beat = np.clip(1.0 - (beat + downbeat), eps, 1.0)
        denom = max(1, self.observation_lambda - 1)
        no_beat = np.clip(no_beat / float(denom), eps, 1.0)

        out = np.empty((len(activations), 3), dtype=np.float64)
        out[:, 0] = np.log(no_beat)
        out[:, 1] = np.log(beat)
        out[:, 2] = np.log(downbeat)
        return out

    def viterbi(self, activations: np.ndarray):
        num_frames = int(len(activations))
        if num_frames == 0:
            return np.empty(0, dtype=np.uint32), float("-inf")

        log_dens = self._log_densities(activations)
        prev = self.initial_log_distribution.copy()
        cur = np.empty_like(prev)

        bt_dtype = np.uint16 if self.num_states <= np.iinfo(np.uint16).max else np.uint32
        backtrack = np.empty((num_frames, self.num_states), dtype=bt_dtype)

        for frame in range(num_frames):
            cur.fill(-np.inf)
            density = log_dens[frame, self.om_pointers]

            cur[self.det_dest] = prev[self.det_prev] + density[self.det_dest]
            backtrack[frame, self.det_dest] = self.det_prev

            for grp in self.boundary_groups:
                scores = prev[grp.prev_states][:, None] + grp.log_transition
                argmax_prev = np.argmax(scores, axis=0)
                best_score = scores[argmax_prev, np.arange(grp.dest_states.size)]
                cur[grp.dest_states] = best_score + density[grp.dest_states]
                backtrack[frame, grp.dest_states] = grp.prev_states[argmax_prev]

            prev, cur = cur, prev

        last_state = int(np.argmax(prev))
        log_probability = float(prev[last_state])
        if math.isinf(log_probability) and log_probability < 0:
            warnings.warn(
                "-inf log probability during Viterbi decoding; cannot find a valid path.",
                RuntimeWarning,
            )
            return np.empty(0, dtype=np.uint32), log_probability

        path = np.empty(num_frames, dtype=np.uint32)
        state = last_state
        for frame in range(num_frames - 1, -1, -1):
            path[frame] = state
            state = int(backtrack[frame, state])
        return path, log_probability


class DBNDownBeatTrackingProcessorPy:
    MIN_BPM = 55.0
    MAX_BPM = 215.0
    NUM_TEMPI = 60
    TRANSITION_LAMBDA = 100
    OBSERVATION_LAMBDA = 16
    THRESHOLD = 0.05
    CORRECT = True

    def __init__(
        self,
        beats_per_bar: Iterable[int],
        min_bpm=MIN_BPM,
        max_bpm=MAX_BPM,
        num_tempi=NUM_TEMPI,
        transition_lambda=TRANSITION_LAMBDA,
        observation_lambda=OBSERVATION_LAMBDA,
        threshold=THRESHOLD,
        correct=CORRECT,
        fps: float = 50.0,
    ):
        beats_per_bar = _as_1d_array(beats_per_bar, dtype=int)
        if beats_per_bar.size == 0:
            raise ValueError("beats_per_bar must not be empty")

        def _expand(x, dtype=float):
            arr = _as_1d_array(x, dtype=dtype)
            if arr.size == beats_per_bar.size:
                return arr
            if arr.size == 1:
                return np.repeat(arr, beats_per_bar.size)
            raise ValueError("All DBN parameter arrays must have same length as beats_per_bar")

        min_bpm = _expand(min_bpm, dtype=float)
        max_bpm = _expand(max_bpm, dtype=float)
        num_tempi = _expand(num_tempi, dtype=int)
        transition_lambda = _expand(transition_lambda, dtype=float)

        self.fps = float(fps)
        self.beats_per_bar = beats_per_bar.astype(int)
        self.threshold = float(threshold)
        self.correct = bool(correct)

        min_interval = 60.0 * self.fps / max_bpm
        max_interval = 60.0 * self.fps / min_bpm

        self.models = []
        for idx, beats in enumerate(self.beats_per_bar):
            st = BarStateSpace(
                int(beats),
                min_interval=float(min_interval[idx]),
                max_interval=float(max_interval[idx]),
                num_intervals=int(num_tempi[idx]),
            )
            t_lambda = [float(transition_lambda[idx])] * int(beats)
            self.models.append(_BarHMMFast(st, t_lambda, int(observation_lambda)))

    def process(self, activations: np.ndarray):
        activations = np.asarray(activations, dtype=np.float64)
        first = 0
        if self.threshold:
            activations, first = threshold_activations(activations, self.threshold)
        if activations.size == 0 or not np.any(np.isfinite(activations)):
            return np.empty((0, 2), dtype=np.float64)

        best_path = None
        best_score = float("-inf")
        best_model = None

        for model in self.models:
            path, log_prob = model.viterbi(activations)
            if best_path is None or log_prob > best_score:
                best_path = path
                best_score = float(log_prob)
                best_model = model

        if best_path is None or best_path.size == 0:
            return np.empty((0, 2), dtype=np.float64)

        st = best_model.state_space
        positions = st.state_positions[best_path]
        beat_numbers = positions.astype(int) + 1

        if self.correct:
            beat_range = best_model.om_pointers[best_path] >= 1
            if not np.any(beat_range):
                return np.empty((0, 2), dtype=np.float64)

            idx = np.nonzero(np.diff(beat_range.astype(np.int8)))[0] + 1
            if beat_range[0]:
                idx = np.r_[0, idx]
            if beat_range[-1]:
                idx = np.r_[idx, beat_range.size]

            peaks = []
            if idx.size > 0:
                for left, right in idx.reshape((-1, 2)):
                    peak = int(np.argmax(activations[left:right]) // 2 + left)
                    peaks.append(peak)
            beats = np.asarray(peaks, dtype=np.int64)
        else:
            beats = np.nonzero(np.diff(beat_numbers))[0] + 1

        if beats.size == 0:
            return np.empty((0, 2), dtype=np.float64)

        return np.vstack(((beats + first) / float(self.fps), beat_numbers[beats])).T


def decode_dbn_from_logits(
    beat_logits,
    downbeat_logits,
    fps: float = 50.0,
    beats_per_bar=(3, 4),
    min_bpm: float = 55.0,
    max_bpm: float = 215.0,
    num_tempi: int = 60,
    transition_lambda: float = 100.0,
    observation_lambda: int = 16,
    threshold: float = 0.05,
    correct: bool = True,
    assume_beat_includes_downbeat: bool = True,
):
    beat_logits = _as_numpy_1d(beat_logits).astype(np.float64)
    downbeat_logits = _as_numpy_1d(downbeat_logits).astype(np.float64)
    if beat_logits.size != downbeat_logits.size:
        raise ValueError("beat_logits and downbeat_logits must have same length")

    beat_prob = _sigmoid(beat_logits)
    downbeat_prob = _sigmoid(downbeat_logits)

    if assume_beat_includes_downbeat:
        beat_prob = np.clip(beat_prob - downbeat_prob, 0.0, 1.0)
    else:
        beat_prob = np.clip(beat_prob, 0.0, 1.0)
    downbeat_prob = np.clip(downbeat_prob, 0.0, 1.0)

    total = beat_prob + downbeat_prob
    over = total > 0.999
    if np.any(over):
        scale = 0.999 / total[over]
        beat_prob[over] *= scale
        downbeat_prob[over] *= scale

    activations = np.stack([beat_prob, downbeat_prob], axis=1)
    proc = DBNDownBeatTrackingProcessorPy(
        beats_per_bar=beats_per_bar,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        num_tempi=num_tempi,
        transition_lambda=transition_lambda,
        observation_lambda=observation_lambda,
        threshold=threshold,
        correct=correct,
        fps=fps,
    )
    beat_and_num = proc.process(activations)
    if beat_and_num.size == 0:
        return (
            np.empty(0, dtype=np.float64),
            np.empty(0, dtype=np.float64),
            np.empty(0, dtype=np.int32),
        )

    beat_times = np.asarray(beat_and_num[:, 0], dtype=np.float64)
    beat_numbers = np.asarray(beat_and_num[:, 1], dtype=np.int32)
    downbeat_times = beat_times[beat_numbers == 1]
    return beat_times, downbeat_times, beat_numbers
