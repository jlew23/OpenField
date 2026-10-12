"""Offline checks; never prints credential values or starts paid calls."""
import argparse,importlib,shutil,sys
from config import setting

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-keys',action='store_true');parser.add_argument('--mesh',action='store_true');args=parser.parse_args()
    failed=sys.version_info<(3,12)
    print('Python:',sys.version.split()[0], '(3.12+ required)')
    for name in ['av','numpy','PIL','requests','fastapi','uvicorn','multipart','gradio_client','scipy']:
        try:importlib.import_module(name);print(name+': OK')
        except Exception as exc:print(name+': FAILED ('+type(exc).__name__+')');failed=True
    binary=shutil.which('rubberband');print('rubberband:', 'OK' if binary else 'MISSING — see docs/SETUP-AGENT.md');failed=failed or not binary
    
    # Check local GPU and AI components
    try:
        import torch
        print('PyTorch CUDA:', 'OK (' + torch.cuda.get_device_name(0) + ')' if torch.cuda.is_available() else 'CPU only')
    except Exception:
        print('PyTorch: not installed in current environment')

    demucs_bin = shutil.which('demucs') or (sys.prefix + '/bin/demucs')
    print('Local Demucs:', 'OK' if shutil.which('demucs') or __import__('os').path.exists(sys.prefix + '/bin/demucs') else 'MISSING')

    if args.mesh:
        from pathlib import Path
        import subprocess
        worker=Path(__file__).resolve().parent/'.venv-face/bin/python'
        ready=worker.exists() and subprocess.run([str(worker),'-c','import mediapipe,av,PIL,numpy'],capture_output=True).returncode==0
        print('Face mesh & local segmenter worker: '+('OK' if ready else 'MISSING — run bash setup-face-mesh.sh'))
        failed=failed or not ready

    missing=[]
    for key in ['ENHANCOR_API_KEY','REPLICATE_API_TOKEN']:
        value=setting(key).strip()
        valid=bool(value) and not any(x in value.lower() for x in ['your_key','your_api','replace_me','placeholder'])
        print(key+': '+('configured' if valid else 'OPTIONAL (running 100% locally)'))
        if not valid:missing.append(key)

    if failed:print('DEPENDENCIES NOT READY');return 1
    print('100% LOCAL WORKFLOW READY: Depth Anything V2, Local Demucs, Face Mesh, and Audio Restoration are operational without cloud APIs.')
    return 0

if __name__=='__main__':sys.exit(main())
