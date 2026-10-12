"""Isolate vocals before generation and replace generated sound with entire original source audio."""
from pathlib import Path
import os,json,time,shutil,subprocess
import av,numpy as np,requests
RATE=44100
ROOT=Path(__file__).resolve().parent

def read_audio(path):
    parts=[];res=av.AudioResampler(format='fltp',layout='stereo',rate=RATE)
    with av.open(str(path)) as c:
        if not c.streams.audio:
            # Generate 1 second of silent audio if no audio stream exists
            return np.zeros((2, RATE), dtype=np.float32)
        for f in c.decode(audio=0):
            parts.extend(x.to_ndarray() for x in res.resample(f))
        parts.extend(x.to_ndarray() for x in res.resample(None))
    return np.concatenate(parts,axis=1) if parts else np.zeros((2, RATE), dtype=np.float32)

def write_audio(path,a):
    with av.open(str(path),'w') as out:
        s=out.add_stream('pcm_s16le',rate=RATE);s.layout='stereo'
        for i in range(0,a.shape[1],4096):
            f=av.AudioFrame.from_ndarray(np.ascontiguousarray(a[:,i:i+4096].astype(np.float32)),format='fltp',layout='stereo');f.sample_rate=RATE;f.pts=i
            for p in s.encode(f):out.mux(p)
        for p in s.encode():out.mux(p)

def separate_local(original, original_wav, folder, status=print):
    demucs_bin = shutil.which('demucs')
    if not demucs_bin:
        possible = ROOT / '.venv/bin/demucs'
        if possible.exists(): demucs_bin = str(possible)
    
    if demucs_bin:
        status('Audio · separating vocals locally with Demucs (CUDA/CPU)')
        try:
            out_dir = folder / 'demucs_out'
            cmd = [demucs_bin, '--two-stems=vocals', '-n', 'htdemucs', '-o', str(out_dir), str(original_wav)]
            subprocess.run(cmd, check=True)
            v_found = list(out_dir.rglob('vocals.wav'))
            m_found = list(out_dir.rglob('no_vocals.wav'))
            if v_found and m_found:
                shutil.copyfile(v_found[0], folder / 'vocals.wav')
                shutil.copyfile(m_found[0], folder / 'music.wav')
                (folder/'audio-manifest.json').write_text(json.dumps({
                    'prediction_id':'local-demucs',
                    'seedance_video':'composite-silent.mp4',
                    'seedance_audio':'vocals.wav',
                    'final_audio':'upload.mp4 (entire original audio track)',
                    'discard_seedance_audio':True,
                    'separation':'Local Demucs htdemucs'
                },indent=2))
                return
        except Exception as e:
            status(f'Local Demucs note: {e}, falling back to audio passthrough')
            
    status('Audio · using original audio track for local vocal guide')
    shutil.copyfile(original_wav, folder / 'vocals.wav')
    shutil.copyfile(original_wav, folder / 'music.wav')
    (folder/'audio-manifest.json').write_text(json.dumps({
        'prediction_id':'local-passthrough',
        'seedance_video':'composite-silent.mp4',
        'seedance_audio':'vocals.wav',
        'final_audio':'upload.mp4 (entire original audio track)',
        'discard_seedance_audio':True,
        'separation':'Direct original audio'
    },indent=2))

def separate(src,folder,status=print):
    folder=Path(folder)
    if (folder/'audio-manifest.json').exists():return
    status('Audio · extracting original track')
    try:
        original=read_audio(src)
    except Exception:
        original=np.zeros((2, RATE), dtype=np.float32)
    write_audio(folder/'original-audio.wav',original)
    token=os.getenv('REPLICATE_API_TOKEN', '').strip()
    if not token or any(x in token.lower() for x in ['your_key','your_api','replace_me','placeholder']):
        separate_local(original, folder/'original-audio.wav', folder, status)
        return
    headers={'Authorization':'Bearer '+token}
    try:
        with (folder/'original-audio.wav').open('rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=headers,files={'content':f},timeout=120)
        r.raise_for_status();url=r.json()['urls']['get'];status('Audio · separating vocals and original music')
        r=requests.post('https://api.replicate.com/v1/predictions',headers=headers,json={'version':'25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953','input':{'audio':url,'model_name':'htdemucs','output_format':'wav'}},timeout=60);r.raise_for_status();j=r.json()
        (folder/'audio-prediction.json').write_text(json.dumps(j,indent=2))
        for _ in range(180):
            if j['status'] in ['succeeded','failed','canceled']:break
            time.sleep(5);r=requests.get(j['urls']['get'],headers=headers,timeout=30);r.raise_for_status();j=r.json()
        if j['status']!='succeeded':
            status('Replicate audio failed, falling back to local: ' + str(j.get('error') or j['status']))
            separate_local(original, folder/'original-audio.wav', folder, status)
            return
        stems={}
        for name,url in j['output'].items():
            if not url:continue
            r=requests.get(url,timeout=120);r.raise_for_status();p=folder/(name+'.wav');p.write_bytes(r.content);stems[name]=read_audio(p)
        if 'vocals' not in stems or not any(n!='vocals' for n in stems):raise ValueError('Separation returned incomplete stems.')
        music=np.zeros_like(original)
        for name,a in stems.items():
            if name!='vocals':n=min(music.shape[1],a.shape[1]);music[:,:n]+=a[:,:n]
        write_audio(folder/'music.wav',np.clip(music,-1,1))
        (folder/'audio-manifest.json').write_text(json.dumps({'prediction_id':j['id'],'seedance_video':'composite-silent.mp4','seedance_audio':'vocals.wav','final_audio':'upload.mp4 (entire original audio track)','discard_seedance_audio':True,'separation':'Demucs htdemucs; residual music or vocal bleed is possible'},indent=2))
    except Exception as e:
        status(f'Replicate error ({e}), falling back to local separation')
        separate_local(original, folder/'original-audio.wav', folder, status)

def finish_preview(generated,folder):
    folder=Path(folder);target=folder/'final-preview.mp4'
    with av.open(str(generated)) as probe, av.open(str(folder/'upload.mp4')) as source:
        stream=probe.streams.video[0]
        vd=float(stream.duration*stream.time_base)
        sd=float(source.duration/av.time_base)
    if 0.25 < sd-vd <= 0.5:
        padded=folder/'seedance-duration-aligned.mp4'
        from fractions import Fraction
        with av.open(str(generated)) as inp,av.open(str(padded),'w') as out:
            video=inp.streams.video[0];rate=video.average_rate or Fraction(24,1)
            stream=out.add_stream('libx264',rate=rate);stream.width=video.width;stream.height=video.height;stream.pix_fmt='yuv420p';stream.options={'crf':'18'}
            frames=list(inp.decode(video=0));count=round(sd*float(rate))
            for i in range(count):
                f=av.VideoFrame.from_ndarray(frames[min(i,len(frames)-1)].to_ndarray(format='rgb24'),format='rgb24');f.pts=i;f.time_base=1/rate
                for packet in stream.encode(f):out.mux(packet)
            for packet in stream.encode():out.mux(packet)
        (folder/'duration-adjustment.json').write_text(json.dumps({'method':'hold final frame','seconds':sd-vd,'original_audio':'unchanged'}))
        generated=padded
    with av.open(str(generated)) as inp,av.open(str(folder/'upload.mp4')) as source_audio,av.open(str(target),'w') as out:
        video=inp.streams.video[0]
        vs=out.add_stream_from_template(video)
        astream=out.add_stream_from_template(source_audio.streams.audio[0]) if source_audio.streams.audio else None
        for p in inp.demux(video=0):
            if p.dts is not None:p.stream=vs;out.mux(p)
        if astream:
            for p in source_audio.demux(audio=0):
                if p.dts is not None:p.stream=astream;out.mux(p)
    return target

def prepare_seedance_video(folder, semitones=3):
    """Embed +3-semitone isolated vocals into the colored-depth composite."""
    folder=Path(folder);binary=shutil.which('rubberband')
    pitched=folder/f'vocals-plus{semitones}.wav'
    if binary and (folder/'vocals.wav').exists():
        try:
            subprocess.run([binary,'--fine','--pitch',str(semitones),'--time','1',str(folder/'vocals.wav'),str(pitched)],check=True,capture_output=True)
            original=read_audio(folder/'vocals.wav');samples=read_audio(pitched)
            n=original.shape[1]
            samples=np.pad(samples,((0,0),(0,max(0,n-samples.shape[1]))))[:,:n]
            write_audio(pitched,samples)
        except Exception:
            if (folder/'vocals.wav').exists():
                shutil.copyfile(folder/'vocals.wav', pitched)
    elif (folder/'vocals.wav').exists():
        shutil.copyfile(folder/'vocals.wav', pitched)
        
    target=folder/'seedance-input.mp4'
    composite_src = folder/'composite.mp4' if (folder/'composite.mp4').exists() else folder/'composite-silent.mp4'
    if not pitched.exists():
        shutil.copyfile(composite_src, target)
        return
        
    try:
        with av.open(str(folder/'composite-silent.mp4')) as video, av.open(str(target),'w') as out:
            vs=out.add_stream_from_template(video.streams.video[0])
            audio=out.add_stream('aac',rate=RATE);audio.layout='stereo';audio.bit_rate=192000
            for packet in video.demux(video=0):
                if packet.dts is not None:packet.stream=vs;out.mux(packet)
            target_resampler=av.AudioResampler(format='fltp',layout='stereo',rate=RATE)
            with av.open(str(pitched)) as p:
                for frame in p.decode(audio=0):
                    for resampled in target_resampler.resample(frame):
                        for packet in audio.encode(resampled):out.mux(packet)
                for resampled in target_resampler.resample(None):
                    for packet in audio.encode(resampled):out.mux(packet)
            for packet in audio.encode():out.mux(packet)
    except Exception as e:
        print("Muxing audio into seedance-input.mp4 fallback:", e)
        shutil.copyfile(composite_src, target)
