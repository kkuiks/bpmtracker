"""Construct only the media used by the explicitly requested U1 interaction audit."""
from array import array
from pathlib import Path
import math
import wave

root = Path(__file__).resolve().parents[4] / '.daw-state/refinement-u1-20261011/media'
root.mkdir(parents=True, exist_ok=True)
rate, seconds = 48000, 30
for index, name in enumerate(['Drums', 'Bass', 'Guitars', 'Vocals']):
    frames = array('h', (round(4500 * math.sin(2 * math.pi * (110 + index * 110) * frame / rate)
        * (.3 + .7 * math.exp(-(frame / rate % .5) * (4 + index)))) for frame in range(rate * seconds)))
    with wave.open(str(root / (name + '.wav')), 'wb') as file:
        file.setnchannels(1); file.setsampwidth(2); file.setframerate(rate); file.writeframes(frames.tobytes())
print('Prepared four audit-owned WAVs; no sample catalog or estimator was used.')
