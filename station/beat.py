"""Beat analysis: tempo, beat grid and a waveform overview from an audio file.

Decodes with PyAV when available, otherwise with the ffmpeg CLI. NumPy only,
so it runs on the same box as the rest of OpenField without librosa.
"""
import shutil, subprocess
import numpy as np

SR = 11025
HOP = 128
NFFT = 1024


def decode(path, sr=SR, max_seconds=600):
    """Mono float32 samples at `sr`."""
    try:
        import av  # noqa: F401
        return _decode_av(path, sr, max_seconds)
    except ImportError:
        pass
    if not shutil.which('ffmpeg'):
        raise RuntimeError('Install ffmpeg (or PyAV) to analyse audio.')
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path), '-t', str(max_seconds), '-ac', '1', '-ar', str(sr),
           '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def _decode_av(path, sr, max_seconds):
    import av
    chunks = []
    with av.open(str(path)) as container:
        stream = next(s for s in container.streams if s.type == 'audio')
        resampler = av.AudioResampler(format='flt', layout='mono', rate=sr)
        total = 0
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                data = out.to_ndarray().reshape(-1)
                chunks.append(data)
                total += data.size
            if total > sr * max_seconds:
                break
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


BANDS = ((0, 200, 1.0), (200, 2000, 1.0), (2000, SR / 2, 0.6))  # Hz range, weight


def onset_envelope(y, sr=SR):
    """Band-wise spectral-flux onset strength, one value per hop.

    Each band is normalised on its own so a kick drum counts as much as a
    bright hi-hat. Frames are centred on their hop position.
    """
    y = np.pad(y, (NFFT // 2, NFFT // 2))
    frames = 1 + (y.size - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(frames)[:, None]
    window = np.hanning(NFFT).astype(np.float32)
    spec = np.log1p(np.abs(np.fft.rfft(y[idx] * window, axis=1)) * 10)
    freqs = np.fft.rfftfreq(NFFT, 1 / sr)
    total = np.zeros(frames, dtype=np.float64)
    for lo, hi, weight in BANDS:
        band = spec[:, (freqs >= lo) & (freqs < hi)]
        if band.shape[1] == 0:
            continue
        flux = np.maximum(0, np.diff(band, axis=0)).sum(axis=1)
        flux = np.concatenate([[0], flux])
        flux -= np.convolve(flux, np.ones(16) / 16, mode='same')  # remove slow trend
        flux = np.maximum(flux, 0)
        peak = flux.max()
        if peak > 0:
            total += weight * flux / peak
    # a centred window sees an onset half a window early; delay to compensate
    total = np.concatenate([[0, 0], total[:-2]])
    peak = total.max()
    return total / peak if peak > 0 else total


def estimate_tempo(env, sr=SR, lo=60, hi=180, prior=110):
    """Tempo in BPM from the onset envelope's autocorrelation, with a mild prior."""
    fps = sr / HOP
    env = env - env.mean()
    n = env.size
    if n < 8:
        return float(prior), 0.0
    spec = np.fft.rfft(env, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    ac /= ac[0] if ac[0] else 1
    lags = np.arange(int(fps * 60 / hi), int(fps * 60 / lo) + 1)
    lags = lags[lags < n]
    if lags.size == 0:
        return float(prior), 0.0
    bpms = 60 * fps / lags
    weight = np.exp(-0.5 * (np.log2(bpms / prior) / 0.8) ** 2)
    score = ac[lags] * weight
    best = int(np.argmax(score))
    # Kick/snare patterns repeat every two beats and hats split each beat, so
    # the neighbouring octaves always correlate as well. Re-decide between the
    # octaves with the tempo prior; the UI offers the alternatives.
    for factor in (0.5, 2.0):
        target = lags[best] * factor
        cand = int(np.argmin(np.abs(lags - target)))
        if abs(lags[cand] - target) <= 1.5 and score[cand] > score[best]:
            best = cand
    lag = lags[best]
    # parabolic refinement
    if 0 < best < len(lags) - 1:
        a, b, c = score[best - 1], score[best], score[best + 1]
        denom = a - 2 * b + c
        if denom:
            lag = lag + 0.5 * (a - c) / denom
    bpm = 60 * fps / lag
    confidence = float(max(0.0, min(1.0, score[best] / (np.abs(score).max() or 1))))
    return float(bpm), confidence


def beat_phase(env, bpm, sr=SR):
    """Offset (seconds) of the first beat that best lines up with onsets."""
    fps = sr / HOP
    period = 60 * fps / bpm
    best_off, best_val = 0.0, -1.0
    steps = max(1, int(period))
    for off in np.linspace(0, period, steps, endpoint=False):
        pos = np.arange(off, env.size, period).astype(int)
        val = env[pos].sum() / max(len(pos), 1)
        if val > best_val:
            best_val, best_off = val, off
    return float(best_off / fps)


def waveform(y, bins=600):
    if y.size == 0:
        return []
    usable = y[: (y.size // bins) * bins] if y.size >= bins else np.pad(y, (0, bins - y.size))
    peaks = np.abs(usable.reshape(bins, -1)).max(axis=1)
    top = peaks.max() or 1
    return [round(float(p / top), 3) for p in peaks]


def analyze(path, hint_bpm=None):
    """{'bpm', 'confidence', 'offset', 'duration', 'beats', 'waveform'} for an audio file."""
    y = decode(path)
    duration = y.size / SR
    env = onset_envelope(y)
    bpm, conf = estimate_tempo(env, prior=hint_bpm or 100)
    if hint_bpm:
        # snap to the hint when we found a simple multiple of it
        for mult in (0.5, 1, 2, 2 / 3, 1.5):
            if abs(bpm - hint_bpm * mult) / (hint_bpm * mult) < 0.04:
                bpm = hint_bpm * mult
                break
    offset = beat_phase(env, bpm)
    period = 60 / bpm
    beats = [round(offset + k * period, 4) for k in range(int((duration - offset) / period) + 1)]
    alternatives = [round(bpm * m, 2) for m in (0.5, 2) if 60 <= bpm * m <= 200]
    return {'bpm': round(bpm, 2), 'confidence': round(conf, 3), 'offset': round(offset, 4),
            'duration': round(duration, 3), 'beats': beats[:4000], 'alternatives': alternatives,
            'waveform': waveform(y)}


def onsets(y, sr=SR, min_gap=0.09):
    """Onset times (seconds) by peak-picking the onset envelope (used for vocal takes)."""
    env = onset_envelope(y, sr)
    if env.size < 3:
        return []
    fps = sr / HOP
    thresh = max(0.12, float(np.percentile(env, 80)))
    gap = int(min_gap * fps)
    out, last = [], -gap
    for i in range(1, env.size - 1):
        if env[i] >= thresh and env[i] >= env[i - 1] and env[i] > env[i + 1] and i - last >= gap:
            out.append(i / fps)
            last = i
    return out


def pocket(path, bpm, offset=0.0, latency_ms=0.0, subdivision=4):
    """How a recorded vocal take sits against the beat grid (16ths by default).

    Positive offset = behind the beat (laid back), negative = ahead (rushing).
    """
    y = decode(path, max_seconds=180)
    times = [t - latency_ms / 1000.0 for t in onsets(y)]
    step = 60.0 / bpm / subdivision
    devs = []
    for t in times:
        if t < offset:
            continue
        rel = (t - offset) / step
        devs.append((rel - round(rel)) * step * 1000)
    if len(devs) < 4:
        return {'ok': False, 'message': 'Not enough syllables detected. Rap closer to the mic, a bit louder.'}
    d = np.array(devs)
    mean, sd = float(d.mean()), float(d.std())
    tight = float((np.abs(d) <= 30).mean())
    if abs(mean) <= 12:
        verdict = 'dead on'
    elif mean > 0:
        verdict = 'behind the beat (laid back)'
    else:
        verdict = 'ahead of the beat (rushing)'
    hist, edges = np.histogram(np.clip(d, -60, 60), bins=12, range=(-60, 60))
    return {'ok': True, 'syllables': len(devs), 'mean_ms': round(mean, 1), 'spread_ms': round(sd, 1),
            'tight': round(tight, 3), 'verdict': verdict, 'histogram': hist.tolist(),
            'edges': [round(float(e)) for e in edges]}
