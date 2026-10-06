"""Create audit-owned media. No catalog/reference files are read or changed."""
from pathlib import Path
import json
import subprocess
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[3] / '.daw-state/audit-20261005'
media = root / 'media'
media.mkdir(parents=True, exist_ok=True)
for rate, channels, name in [(48000, 1, 'mono48.wav'), (44100, 2, 'stereo44.wav'), (96000, 2, 'stereo96.flac')]:
    times = np.arange(round(8.5 * rate)) / rate
    left = .14 * np.sin(2 * np.pi * 220 * times)
    if channels == 2:
        signal = np.column_stack((left, .11 * np.sin(2 * np.pi * 330 * times)))
    else:
        signal = left
    sf.write(media / name, signal, rate, subtype='PCM_24')
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(media/'stereo44.wav'), str(media/'stereo44.mp3')], check=True)
# Fixed synthetic musical pulse train exercises adapter plumbing, not unseen-song accuracy.
rate = 44100
times = np.arange(rate * 24) / rate
step = 60/160
beat = np.floor((times-.137)/step + 1e-9).astype(int)
age = times - (.137 + beat*step)
strong = beat % 4 == 0
signal = np.where((age >= 0) & (age < .09), np.sin(2*np.pi*np.where(strong,110,880)*age)*np.exp(-np.maximum(age,0)/.02)*np.where(strong,.7,.45), 0)
sf.write(media/'synthetic160.wav', signal, rate, subtype='PCM_24')
(media/'corrupt.wav').write_bytes(b'not an audio file')
sf.write(media/'unsupported-4ch.wav', np.zeros((480,4)),48000)
sf.write(media/'한글 이름 with spaces.flac', np.column_stack((signal,signal)),rate)
print(json.dumps({'media':str(media),'files':sorted(p.name for p in media.iterdir())}))
