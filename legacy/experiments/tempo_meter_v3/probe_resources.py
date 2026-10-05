"""Measure local observation and untrained-head cost, never model accuracy.

Audio is streamed with context; this is not the future map inference pipeline.
The learned structure model and joint decoder do not exist at this gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import time


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from beat_this.inference import Audio2Frames
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=600)
    args = p.parse_args()
    if args.output.exists() or not args.checkpoint.is_file():
        p.error('fresh output and existing local checkpoint required')
    if not np.isfinite(args.seconds) or args.seconds <= 0:
        p.error('seconds must be positive')
    if not torch.cuda.is_available():
        p.error('CUDA required for the approved hardware feasibility probe')
    torch.set_num_threads(4)
    torch.manual_seed(20260930)
    info = sf.info(args.audio)
    frames = min(info.frames, round(args.seconds * info.samplerate))
    record = dict(kind='resource_probe_not_analyzer', complete=False,
                  audio=str(args.audio.resolve()), audio_sha256=digest(args.audio),
                  checkpoint_sha256=digest(args.checkpoint),
                  runner_sha256=digest(__file__), source_frames=info.frames,
                  analyzed_frames=frames, sample_rate=info.samplerate,
                  source_frame_offset=0, device=torch.cuda.get_device_name(),
                  total_device_bytes=torch.cuda.get_device_properties(0).total_memory,
                  torch_version=torch.__version__, platform=platform.platform(),
                  head_trained=False, decoder_included=False, accuracy_scored=False,
                  full_pipeline_30_minute_gate='not_yet_measured', chunks=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')
    save()
    start = time.perf_counter()
    try:
        torch.cuda.reset_peak_memory_stats()
        model = Audio2Frames(str(args.checkpoint.resolve()), 'cuda', float16=False)
        dim = model.model.task_heads.in_features if hasattr(model.model.task_heads, 'in_features') else 512
        # The hook verifies the actual feature dimension before using the head.
        head = torch.nn.Sequential(torch.nn.Linear(dim, 128),
            torch.nn.TransformerEncoder(torch.nn.TransformerEncoderLayer(
                128, 4, dim_feedforward=512, dropout=0, batch_first=True), 4),
            torch.nn.Linear(128, 8)).cuda().eval()
        feature_shapes = []
        def consume_features(module, inputs, value):
            # Every fourth frame; no learned labels, scores or map are produced.
            pooled = value[:, ::4, :]
            if pooled.shape[-1] != dim:
                raise ValueError('unexpected acoustic feature dimension')
            result = head(pooled)
            if not torch.isfinite(result).all():
                raise ValueError('nonfinite structural probe output')
            feature_shapes.append(list(value.shape))
        hook = model.model.transformer_blocks.register_forward_hook(consume_features)
        torch.cuda.synchronize()
        record['load_seconds'] = time.perf_counter()-start
        hop = 24 * info.samplerate
        context = 4 * info.samplerate
        for first in range(0, frames, hop):
            left, right = max(0, first-context), min(frames, first+hop+context)
            began = time.perf_counter()
            signal, sr = sf.read(args.audio, start=left, stop=right, dtype='float32', always_2d=True)
            with torch.inference_mode():
                beat, down = model(signal, sr)
            torch.cuda.synchronize()
            if not torch.isfinite(beat).all() or not torch.isfinite(down).all():
                raise ValueError('nonfinite observations')
            record['chunks'].append(dict(start_frame=left, end_frame=right,
                seconds=time.perf_counter()-began, feature_shapes=feature_shapes[:]))
            feature_shapes.clear()
            del signal, beat, down
            save()
            print(f'probe {min(first+hop,frames)/sr:.1f}/{frames/sr:.1f}s', flush=True)
        hook.remove()
        record['complete'] = True
    except Exception as exc:
        record['error'] = {'type':type(exc).__name__, 'message':str(exc)}
        raise
    finally:
        record.update(elapsed_seconds=time.perf_counter()-start,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        record['real_time_factor'] = record['elapsed_seconds'] / (frames/info.samplerate)
        save()
    print(json.dumps({k:record[k] for k in ['complete','elapsed_seconds','real_time_factor','peak_reserved_bytes','max_rss_bytes']}))


if __name__ == '__main__':
    main()
