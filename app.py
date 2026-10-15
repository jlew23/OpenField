from pathlib import Path
import threading,uuid,shutil,json,os,time,subprocess,traceback
from fastapi import FastAPI,UploadFile,File,Form,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pipeline import run
ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'runs';RUNS.mkdir(exist_ok=True)
def to_win_path(p):
    s = str(Path(p).resolve())
    if shutil.which('wslpath'):
        try:
            return subprocess.check_output(['wslpath', '-w', s], text=True).strip()
        except Exception:
            pass
    return s


app=FastAPI();jobs={}
@app.get('/')
def index():return FileResponse(ROOT/'static/index.html')

@app.post('/jobs')
def create(video:UploadFile=File(...),prompt:str=Form('person'),provider:str=Form('local'),mode:str=Form('depth')):
    if mode not in ['depth','face_mesh','depth_mesh']:raise HTTPException(400,'Unknown workflow mode')
    if provider not in ['local','huggingface','replicate','replicate-chenxwh']:raise HTTPException(400,'Unknown provider')
    ident=uuid.uuid4().hex;folder=RUNS/ident;folder.mkdir();src=folder/'upload.mp4'
    with src.open('wb') as out:shutil.copyfileobj(video.file,out)
    
    init_msg = f"[{time.strftime('%H:%M:%S')}] Job created: {ident} (Mode: {mode}, Provider: {provider})"
    jobs[ident]={
        'state':'running',
        'status':'Starting',
        'id':ident,
        'logs':[init_msg],
        'folder_path':to_win_path(folder)
    }
    (folder/'job.log').write_text(init_msg + '\n')
    (folder/'status.json').write_text(json.dumps(jobs[ident]))

    def log_status(s):
        line = f"[{time.strftime('%H:%M:%S')}] {s}"
        print(line, flush=True)
        if ident in jobs:
            jobs[ident]['status'] = s
            jobs[ident].setdefault('logs', []).append(line)
            (folder/'status.json').write_text(json.dumps(jobs[ident]))
            with (folder/'job.log').open('a') as lf:
                lf.write(line + '\n')

    def work():
        try:
            log_status("Starting preparation pipeline...")
            if mode=='face_mesh':
                from face_mesh import run as run_mesh
                run_mesh(src,folder,log_status)
            elif mode=='depth_mesh':
                from face_mesh import run_depth
                run_depth(src,folder,prompt,provider,log_status)
            else:
                run(src,folder,prompt,provider,log_status)
            log_status("Preparation COMPLETE! All files ready in run folder.")
            jobs[ident].update(state='done',status='Preparation complete · input review required')
            (folder/'status.json').write_text(json.dumps(jobs[ident]))
        except Exception as e:
            err_trace = traceback.format_exc()
            log_status(f"ERROR: {str(e)}")
            with (folder/'job.log').open('a') as lf:
                lf.write(err_trace + '\n')
            jobs[ident].update(state='error',status=f"Failed: {str(e)}")
            jobs[ident].setdefault('logs', []).append(f"[{time.strftime('%H:%M:%S')}] Traceback:\n{err_trace}")
            (folder/'status.json').write_text(json.dumps(jobs[ident]))

    threading.Thread(target=work,daemon=True).start()
    return jobs[ident]

@app.get('/jobs/{ident}')
def get(ident:str):
    if ident not in jobs:
        if len(ident)==32 and all(c in '0123456789abcdef' for c in ident) and (RUNS/ident/'status.json').exists():
            data = json.loads((RUNS/ident/'status.json').read_text())
            log_file = RUNS/ident/'job.log'
            if log_file.exists():
                data['logs'] = [l.strip() for l in log_file.read_text().splitlines() if l.strip()]
            data['folder_path'] = to_win_path(RUNS/ident)
            return data
        raise HTTPException(404)
    return jobs[ident]

@app.post('/jobs/{ident}/open-folder')
def open_folder(ident:str):
    if len(ident)!=32 or not (RUNS/ident).exists():raise HTTPException(404)
    target = (RUNS/ident).resolve()
    win_path = to_win_path(target)
    try:
        subprocess.run(['cmd.exe', '/c', 'start', '""', win_path], check=False)
    except Exception:
        try:
            subprocess.run(['explorer.exe', win_path], check=False)
        except Exception:
            pass
    return {'folder_path': win_path}

@app.post('/jobs/{ident}/seedance')
def seedance(ident:str,prompt:str=Form(...),sirio:UploadFile=File(...),tein:UploadFile|None=File(None),api_key:str|None=Form(None)):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    if api_key and api_key.strip():
        os.environ['ENHANCOR_API_KEY'] = api_key.strip()
    key = os.getenv('ENHANCOR_API_KEY', '').strip()
    if not key or any(x in key.lower() for x in ['your_key','your_api','replace_me','placeholder']):
        raise HTTPException(400, "Image-to-Video Model API key is required. Please insert your API key in Section 03.")
    if not (folder/'audio-manifest.json').exists():raise HTTPException(400,'Audio separation must complete first.')
    from mask_review import require_approved
    try:require_approved(folder)
    except ValueError as e:raise HTTPException(409,str(e))
    paths=[]
    for name,upload in [('sirio-reference',sirio),('tein-reference',tein)]:
        if upload is None:
            paths.append(None)
            continue
        suffix=Path(upload.filename or '').suffix.lower()
        if suffix not in (['.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm'] if name=='sirio-reference' else ['.png','.jpg','.jpeg','.webp']):raise HTTPException(400,'Use an image or a Sirio reference video.')
        path=folder/(name+suffix)
        with path.open('wb') as f:shutil.copyfileobj(upload.file,f)
        paths.append(path)
    from seedance_bridge import submit
    try:request_id=submit(folder,prompt,*paths)
    except Exception as e:raise HTTPException(502,str(e))
    jobs[ident]={'id':ident,'state':'running','status':'Seedance rendering: '+request_id}
    def collect():
        from seedance_bridge import wait_and_finish
        try:
            wait_and_finish(folder,request_id,lambda s:jobs[ident].update(status=s))
            jobs[ident].update(state='done',status='Final preview ready · entire original source audio',final_url='/runs/'+ident+'/final-preview.mp4')
        except Exception as e:jobs[ident].update(state='error',status=str(e))
        (folder/'status.json').write_text(json.dumps(jobs[ident]))
    threading.Thread(target=collect,daemon=True).start()
    return {'request_id':request_id,'id':ident,'state':'running','status':jobs[ident]['status']}

@app.post('/jobs/{ident}/finish')
def finish(ident:str,video:UploadFile=File(...)):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    if not (folder/'upload.mp4').exists():raise HTTPException(400,'Original source is required.')
    target=folder/'seedance-result.mp4'
    with target.open('wb') as f:shutil.copyfileobj(video.file,f)
    from audio_workflow import finish_preview
    try:
        finish_preview(target,folder)
    except Exception as e:
        raise HTTPException(400,str(e))
    return {'url':'/runs/'+ident+'/final-preview.mp4'}

app.mount('/runs' ,StaticFiles(directory=RUNS),name='runs')

hd_jobs={}
hd_lock=threading.Lock()

def hd_folder(ident):
    if len(ident)!=32 or not all(c in '0123456789abcdef' for c in ident):raise HTTPException(404)
    folder=RUNS/ident
    if not folder.exists():raise HTTPException(404)
    return folder

@app.get('/jobs/{ident}/hd')
def get_hd(ident:str):
    folder=hd_folder(ident)
    if ident in hd_jobs:return hd_jobs[ident]
    saved=folder/'hd/status.json'
    if saved.exists():return json.loads(saved.read_text())
    return {'state':'idle','status':'Approve your draft to generate 1080p.'}

@app.post('/jobs/{ident}/hd')
def create_hd(ident:str):
    folder=hd_folder(ident)
    key = os.getenv('ENHANCOR_API_KEY', '').strip()
    if not key or any(x in key.lower() for x in ['your_key','your_api','replace_me','placeholder']):
        raise HTTPException(400, "Enhancor API key is not configured.")
    with hd_lock:
        previous=get_hd(ident)
        if previous['state'] in ['running','done']:return previous
        if not (folder/'final-preview.mp4').exists():raise HTTPException(400,'Complete and review a draft first.')
        hd=folder/'hd';hd.mkdir(exist_ok=True)
        hd_jobs[ident]={'state':'running','status':'Submitting approved draft for 1080p','id':ident}
        def save(): (hd/'status.json').write_text(json.dumps(hd_jobs[ident]))
        save()
    def work_hd():
        from seedance_bridge import submit_hd,wait_and_finish
        try:
            request_id=submit_hd(folder)
            hd_jobs[ident].update(request_id=request_id,status='Generating 1080p through Enhancor');save()
            wait_and_finish(hd,request_id,lambda s:hd_jobs[ident].update(status=s))
            hd_jobs[ident].update(state='done',status='1080p ready · original source audio restored')
        except Exception as e:hd_jobs[ident].update(state='error',status=str(e))
        save()
    threading.Thread(target=work_hd,daemon=True).start()
    return hd_jobs[ident]

@app.get('/jobs/{ident}/mask-review')
def get_mask_review(ident:str):
    from mask_review import state
    return state(hd_folder(ident))

@app.post('/jobs/{ident}/mask-review')
def save_mask_review(ident:str,approved:bool=Form(...),fingerprint:str=Form(...),note:str=Form('')):
    from mask_review import review
    try:return review(hd_folder(ident),approved,note,fingerprint)
    except ValueError as e:raise HTTPException(409,str(e))

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.on_event('startup')
def resume_saved_generations():
    """Resume collection only: never requeue a paid prediction on restart."""
    from seedance_bridge import wait_and_finish
    for root in RUNS.iterdir():
        if not root.is_dir() or len(root.name)!=32:continue
        for folder,response_file,registry in [(root,'seedance-response.json',jobs),(root/'hd','response.json',hd_jobs)]:
            response=folder/response_file
            if not response.exists() or (folder/'final-preview.mp4').exists():continue
            try:request_id=json.loads(response.read_text()).get('requestId')
            except (ValueError,OSError):continue
            if not request_id:continue
            registry[root.name]={'id':root.name,'state':'running','status':'Resuming saved request '+request_id}
            def collect_saved(folder=folder,ident=root.name,request_id=request_id,registry=registry):
                try:
                    wait_and_finish(folder,request_id,lambda message:registry[ident].update(status=message))
                    registry[ident].update(state='done',status='Final preview ready · original source audio')
                except Exception as e:registry[ident].update(state='error',status=str(e))
                (folder/'status.json').write_text(json.dumps(registry[ident]))
            threading.Thread(target=collect_saved,daemon=True).start()

@app.get('/health')
def health():
    return {'status':'ok','service':'TEIN Video Workflow'}
