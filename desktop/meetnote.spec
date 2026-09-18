# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙: MeetNote 데스크톱(exe). 빌드: desktop\build-exe.ps1
import os, glob
from PyInstaller.utils.hooks import collect_all, collect_submodules
root = os.path.abspath(os.path.join(SPECPATH, '..'))
datas, binaries, hidden = [], [], []
for pkg in ['faster_whisper', 'ctranslate2', 'tokenizers', 'huggingface_hub', 'resemblyzer', 'librosa', 'sklearn', 'scipy', 'soundfile', 'numpy', 'webrtcvad', 'torch', 'torchaudio', 'lazy_loader', 'numba', 'llvmlite', 'onnxruntime', 'imageio_ffmpeg']:
    try:
        d, b, h = collect_all(pkg); datas += d; binaries += b; hidden += h
    except Exception as e:
        print('skip', pkg, e)
hidden += collect_submodules('uvicorn') + collect_submodules('fastapi') + collect_submodules('starlette') + ['multipart', 'python_multipart', 'anyio._backends._asyncio']
# 발언자 구분 부품: C 확장과 하위 모듈을 명시 (webrtcvad-wheels, resemblyzer, libsndfile DLL, 동봉 ffmpeg)
hidden += ['_webrtcvad', 'webrtcvad', 'resemblyzer', 'resemblyzer.audio', 'resemblyzer.voice_encoder', 'resemblyzer.hparams', 'soundfile', '_soundfile_data', 'imageio_ffmpeg']
for pkg in ['_soundfile_data', 'imageio_ffmpeg', 'resemblyzer']:
    try:
        d, b, h = collect_all(pkg); datas += d; binaries += b; hidden += h
    except Exception as e:
        print('skip', pkg, e)
try:
    import importlib, glob as _g
    for name in ['webrtcvad', 'imageio_ffmpeg', 'resemblyzer', '_soundfile_data']:
        m = importlib.import_module(name)
        base = os.path.dirname(m.__file__)
        for f in _g.glob(os.path.join(base, '**', '*'), recursive=True):
            if os.path.isfile(f) and f.endswith(('.pyd', '.dll', '.exe', '.pt', '.so')):
                rel = os.path.relpath(os.path.dirname(f), os.path.dirname(base))
                (binaries if f.endswith(('.pyd', '.dll', '.so')) else datas).append((f, rel))
except Exception as e:
    print('extra collect skipped:', e)
datas.append((os.path.join(root, 'web'), 'web'))
for ff in glob.glob(os.path.join(root, 'server', 'ffmpeg*', '**', 'ffmpeg.exe'), recursive=True):
    binaries.append((ff, 'ffmpeg')); break
a = Analysis([os.path.join(root, 'server', 'diarize.py')], pathex=[root], hookspath=[os.path.join(SPECPATH, 'hooks')], binaries=binaries, datas=datas, hiddenimports=hidden, excludes=['tkinter', 'matplotlib', 'PyQt5', 'PySide2', 'IPython', 'notebook'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MeetNote', console=True, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MeetNote')
