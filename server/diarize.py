"""
MeetNote 발언자 구분 서비스 (로컬 파이썬)
- 전사: faster-whisper (기본 small, 환경변수 WHISPER_MODEL로 변경)
- 발언자 구분: 1) pyannote.audio 3.1 (HF_TOKEN 있을 때, 가장 정확)
              2) resemblyzer 임베딩 + 군집 (토큰 없이, CPU)
              3) 둘 다 없으면 화자 1명으로 반환
실행: pip install -r requirements.txt && python diarize.py   (http://localhost:8765)
"""
import os, sys, tempfile, subprocess, shutil, threading, time, uuid, webbrowser
# PyInstaller exe에서 ctranslate2(Whisper)와 torch(resemblyzer)의 OpenMP 런타임 충돌·numba 캐시 문제 방지
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", str(max(1, min(8, (os.cpu_count() or 4) // 2))))
os.environ.setdefault("MKL_NUM_THREADS", os.environ["OMP_NUM_THREADS"])
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "meetnote-numba"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
DEVICE = os.environ.get("DEVICE", "auto")          # auto | cpu | cuda
COMPUTE = os.environ.get("COMPUTE", "int8")         # int8 (CPU) | float16 (GPU)
HF_TOKEN = os.environ.get("HF_TOKEN", "")
DIARIZER = os.environ.get("DIARIZER", "auto")   # auto | none (전사만)
BEAM = int(os.environ.get("BEAM_SIZE", "5"))
PORT = int(os.environ.get("PORT", "8765"))
PRELOAD = os.environ.get("PRELOAD", "1") != "0"   # 시작 시 모델을 미리 내려받아 첫 분석을 빠르게
MODEL_SIZE = {"tiny": "75", "base": "145", "small": "460", "medium": "1500", "large-v3": "3000"}

def _base_dir():
    """실행 위치: 소스 실행이면 server/, PyInstaller exe면 압축이 풀린 임시 폴더."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

def _find_ffmpeg():
    if shutil.which("ffmpeg"): return
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    roots = [os.path.join(exe_dir, "ffmpeg"), exe_dir, os.path.join(_base_dir(), "ffmpeg"), os.path.join(exe_dir, "..", "ffmpeg"), r"C:\ffmpeg", os.path.expanduser("~/ffmpeg")]
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for root in roots:
        if not os.path.isdir(root): continue
        for dp, _, fn in os.walk(root):
            if name in fn:
                os.environ["PATH"] = dp + os.pathsep + os.environ.get("PATH", "")
                print(f"[ffmpeg] {dp} 사용"); return
    try:  # pip 패키지에 동봉된 ffmpeg (imageio-ffmpeg)
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        d = os.path.dirname(exe)
        if os.path.basename(exe) != name:  # 파일 이름이 ffmpeg-win64-v7.x.exe 형태라 심볼릭 복사
            link = os.path.join(tempfile.gettempdir(), "meetnote-ffmpeg"); os.makedirs(link, exist_ok=True)
            dst = os.path.join(link, name)
            if not os.path.exists(dst): shutil.copy2(exe, dst)
            d = link
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        print(f"[ffmpeg] imageio-ffmpeg 동봉본 사용 ({d})")
    except Exception:
        pass
_find_ffmpeg()

WEB_DIR = next((d for d in [os.path.join(_base_dir(), "web"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")] if os.path.isfile(os.path.join(d, "index.html"))), None)

app = FastAPI(title="MeetNote diarize")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_whisper = None
_pyannote = None
_encoder = None

def load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        dev = DEVICE
        if dev == "auto":
            try:
                import torch; dev = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                dev = "cpu"
        comp = COMPUTE if dev == "cpu" else ("float16" if COMPUTE == "int8" else COMPUTE)
        _whisper = WhisperModel(WHISPER_MODEL, device=dev, compute_type=comp)
        print(f"[whisper] {WHISPER_MODEL} on {dev} ({comp})")
    return _whisper

def load_pyannote():
    global _pyannote
    if _pyannote is None and HF_TOKEN:
        try:
            from pyannote.audio import Pipeline
            _pyannote = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_TOKEN)
            try:
                import torch
                if torch.cuda.is_available(): _pyannote.to(torch.device("cuda"))
            except Exception: pass
            print("[diarizer] pyannote/speaker-diarization-3.1")
        except Exception as e:
            print("[diarizer] pyannote 사용 불가:", e)
    return _pyannote

def load_encoder():
    global _encoder
    if DIARIZER == "none": return None
    if _encoder is None:
        try:
            try:
                import torch; torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
            except Exception: pass
            from resemblyzer import VoiceEncoder
            _encoder = VoiceEncoder()
            print("[diarizer] resemblyzer fallback")
        except Exception as e:
            print("[diarizer] resemblyzer 사용 불가:", e)
    return _encoder

def to_wav(src_path: str) -> str:
    """어떤 형식이든 16kHz mono wav로 (ffmpeg 필요)."""
    if not shutil.which("ffmpeg"):
        raise HTTPException(500, "ffmpeg가 없어요. https://ffmpeg.org 에서 설치하고 PATH에 넣어 주세요.")
    out = src_path + ".16k.wav"
    r = subprocess.run(["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "16000", "-vn", out], capture_output=True)
    if r.returncode != 0:
        raise HTTPException(400, "오디오를 변환하지 못했어요: " + r.stderr.decode(errors="ignore")[-300:])
    return out

def read_wav(path: str):
    import soundfile as sf
    wav, sr = sf.read(path, dtype="float32")
    if wav.ndim > 1: wav = wav.mean(axis=1)
    return wav, sr

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))

def assign_speakers(segments, turns):
    """turns: [(t0, t1, label)] → 각 전사 구간에 가장 많이 겹치는 화자."""
    labels = sorted({t[2] for t in turns})
    idx = {l: str(i) for i, l in enumerate(labels)}
    out = []
    for s in segments:
        best, bt = None, 0.0
        for t0, t1, lab in turns:
            o = overlap(s["t0"], s["t1"], t0, t1)
            if o > bt: best, bt = lab, o
        if best is None:  # 겹침이 없으면 가장 가까운 turn
            best = min(turns, key=lambda t: min(abs(t[0] - s["t0"]), abs(t[1] - s["t1"])))[2] if turns else labels[0] if labels else "0"
        out.append({**s, "spk": idx.get(best, "0")})
    return out

def diarize_pyannote(wav_path, num_speakers):
    pipe = load_pyannote()
    if pipe is None: return None
    kw = {"num_speakers": num_speakers} if num_speakers else {}
    ann = pipe(wav_path, **kw)
    return [(seg.start, seg.end, lab) for seg, _, lab in ann.itertracks(yield_label=True)]

def diarize_embeddings(wav, sr, segments, num_speakers, progress=None, cancelled=lambda: False):
    enc = load_encoder()
    if enc is None or not segments: return None
    from resemblyzer import preprocess_wav
    embs, keep = [], []
    t0 = time.time(); n = len(segments)
    for i, s in enumerate(segments):
        if cancelled(): raise Cancelled()
        a, b = int(s["t0"] * sr), int(s["t1"] * sr)
        chunk = wav[a:b]
        if len(chunk) < sr * 0.6: continue
        try:
            embs.append(enc.embed_utterance(preprocess_wav(chunk, source_sr=sr)))
            keep.append(s)
        except Exception as e:
            print("[embeddings] 구간 건너뜀:", e); continue
        if progress and (i % 3 == 0 or i == n - 1):
            progress(80 + 14 * (i + 1) / n, "diarize", f"목소리 특징 비교 {i + 1}/{n}")
        if i == 0: print(f"[embeddings] 첫 구간 {time.time() - t0:.1f}s (torch 초기화 포함)")
    print(f"[embeddings] {len(keep)}구간 {time.time() - t0:.1f}s")
    if len(embs) < 2: return [(s["t0"], s["t1"], "0") for s in segments]
    X = np.stack(embs)
    from sklearn.cluster import AgglomerativeClustering
    if num_speakers:
        cl = AgglomerativeClustering(n_clusters=min(num_speakers, len(X)), metric="cosine", linkage="average")
    else:
        cl = AgglomerativeClustering(n_clusters=None, distance_threshold=0.42, metric="cosine", linkage="average")
    labels = cl.fit_predict(X)
    return [(s["t0"], s["t1"], str(l)) for s, l in zip(keep, labels)]

class Cancelled(Exception): pass

def run_pipeline(src_path: str, lang: Optional[str], num_speakers: Optional[int], progress=lambda pct, stage, msg="": None, cancelled=lambda: False):
    """전체 파이프라인. progress(pct 0~100, stage, message) 콜백으로 진행률 보고."""
    def check():
        if cancelled(): raise Cancelled()
    progress(8, "convert", "오디오를 16kHz로 변환하는 중")
    wav_path = to_wav(src_path); check()
    if _whisper is None:
        progress(12, "model", f"음성 인식 모델({WHISPER_MODEL})을 처음 내려받는 중 — 서버 창에 다운로드 진행률이 표시돼요 (약 {MODEL_SIZE.get(WHISPER_MODEL, '수백')}MB)")
    else:
        progress(14, "model", "음성 인식 모델 준비 중")
    model = load_whisper(); check()
    progress(16, "transcribe", "전사 준비 중 (음성 구간 탐지)")
    # 환청(말이 없는데 같은 단어가 반복되는 현상) 억제: VAD로 무음 제거, 앞 문장에 끌려가지 않게, 같은 구절 재생성 금지, 압축률·확률이 나쁜 구간은 버림
    kw = dict(language=(lang or None) if lang != "auto" else None, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
              beam_size=BEAM, condition_on_previous_text=False, no_repeat_ngram_size=6, repetition_penalty=1.05,
              compression_ratio_threshold=2.2, log_prob_threshold=-1.0, no_speech_threshold=0.6)
    try:
        segs_iter, info = model.transcribe(wav_path, **kw)
    except TypeError:   # 오래된 faster-whisper: 모르는 인자는 빼고
        for k in ("no_repeat_ngram_size", "repetition_penalty", "vad_parameters"): kw.pop(k, None)
        segs_iter, info = model.transcribe(wav_path, **kw)
    dur = float(getattr(info, "duration", 0) or 0)
    mm = lambda t: f"{int(t // 60):02d}:{int(t % 60):02d}"
    dev = getattr(getattr(model, "model", None), "device", None) or ("cuda" if DEVICE == "cuda" else "cpu")
    est = f" · {'GPU' if str(dev).startswith('cuda') else 'CPU'}에서는 약 {max(1, int(dur / 60 * (0.1 if str(dev).startswith('cuda') else 0.5)))}~{max(2, int(dur / 60 * (0.2 if str(dev).startswith('cuda') else 1.0)))}분 예상" if dur else ""
    progress(17, "transcribe", f"전사 시작 (녹음 {mm(dur)}{est}). 첫 문장이 나오면 시간이 올라가요.")
    print(f"[transcribe] 녹음 {mm(dur)} 시작{est}")
    segments = []
    t_last = time.time()
    for sg in segs_iter:
        check()
        if sg.text.strip():
            segments.append({"t0": round(sg.start, 2), "t1": round(sg.end, 2), "text": sg.text.strip()})
        if dur > 0:
            progress(16 + min(54, 54 * sg.end / dur), "transcribe", f"전사 중 {mm(sg.end)} / {mm(dur)}")
        if time.time() - t_last > 10:
            t_last = time.time(); print(f"[transcribe] {mm(sg.end)} / {mm(dur)} ({len(segments)}문장)")
    progress(72, "diarize", "발언자 분석 준비 중"); check()
    print(f"[transcribe] 완료 {len(segments)}문장")
    turns = None
    if DIARIZER == "none":
        print("[diarize] DIARIZER=none → 발언자 분석 건너뜀")
        progress(95, "finalize", "정리 중")
        return {"language": getattr(info, "language", lang), "duration": dur or None, "segments": [{**s, "spk": "0"} for s in segments], "diarizer": "none"}
    try:
        turns = diarize_pyannote(wav_path, num_speakers)
    except Exception as e:
        print("[pyannote] 실패:", e)
    check()
    if turns is None:
        try:
            t_r = time.time(); wav, sr = read_wav(wav_path); print(f"[diarize] 오디오 읽기 {time.time() - t_r:.1f}s")
            progress(80, "diarize", "목소리 특징을 비교하는 중")
            turns = diarize_embeddings(wav, sr, segments, num_speakers, progress, cancelled)
        except Cancelled:
            raise
        except Exception as e:
            print("[embeddings] 실패:", e)
    check()
    progress(95, "finalize", "정리 중")
    if turns:
        segments = assign_speakers(segments, turns)
    else:
        segments = [{**s, "spk": "0"} for s in segments]
    progress(100, "done", "완료")
    return {"language": getattr(info, "language", lang), "duration": dur or None, "segments": segments,
            "diarizer": "pyannote" if (HF_TOKEN and _pyannote) else ("resemblyzer" if _encoder else "none")}

@app.post("/diarize")
async def diarize(audio: UploadFile = File(...), lang: Optional[str] = Form("ko"), num_speakers: Optional[int] = Form(None)):
    """동기 API (구버전 호환)."""
    tmpdir = tempfile.mkdtemp(prefix="meetnote_")
    try:
        src = os.path.join(tmpdir, audio.filename or "audio.bin")
        with open(src, "wb") as f: f.write(await audio.read())
        return run_pipeline(src, lang, num_speakers)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ---- 진행률을 보고하는 작업(job) API ----
JOBS = {}
JOBS_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()   # 분석은 한 번에 하나만 (CPU 경쟁 방지)

def _job_worker(job_id: str, src: str, tmpdir: str, lang, num_speakers):
    job = JOBS[job_id]
    def progress(pct, stage, msg=""):
        job.update({"pct": round(float(pct), 1), "stage": stage, "message": msg, "updated": time.time()})
    try:
        if not RUN_LOCK.acquire(blocking=False):
            job.update({"stage": "queued", "message": "앞 작업이 끝나길 기다리는 중", "pct": 3})
            while not RUN_LOCK.acquire(timeout=0.5):
                if job.get("cancel"): raise Cancelled()
        if job.get("cancel"): raise Cancelled()
        job["state"] = "running"
        result = run_pipeline(src, lang, num_speakers, progress, lambda: job.get("cancel", False))
        job.update({"state": "done", "result": result, "pct": 100, "stage": "done", "message": "완료"})
    except Cancelled:
        job.update({"state": "cancelled", "message": "취소됨"})
    except HTTPException as e:
        job.update({"state": "error", "error": str(e.detail)})
    except Exception as e:
        job.update({"state": "error", "error": f"{type(e).__name__}: {e}"})
    finally:
        try: RUN_LOCK.release()
        except RuntimeError: pass
        shutil.rmtree(tmpdir, ignore_errors=True)
        job["finished"] = time.time()

def _gc_jobs():
    now = time.time()
    with JOBS_LOCK:
        for k in [k for k, j in JOBS.items() if j.get("finished") and now - j["finished"] > 900]:
            JOBS.pop(k, None)

@app.post("/jobs")
async def create_job(audio: UploadFile = File(...), lang: Optional[str] = Form("ko"), num_speakers: Optional[int] = Form(None)):
    _gc_jobs()
    tmpdir = tempfile.mkdtemp(prefix="meetnote_")
    src = os.path.join(tmpdir, audio.filename or "audio.bin")
    with open(src, "wb") as f: f.write(await audio.read())
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"id": job_id, "state": "queued", "pct": 3, "stage": "queued", "message": "대기 중", "created": time.time()}
    threading.Thread(target=_job_worker, args=(job_id, src, tmpdir, lang, num_speakers), daemon=True).start()
    return {"job_id": job_id}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(404, "없는 작업이에요.")
    out = {k: v for k, v in job.items() if k not in ("cancel",)}
    if job["state"] != "done": out.pop("result", None)
    return out

@app.delete("/jobs/{job_id}")
def cancel_job(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(404, "없는 작업이에요.")
    job["cancel"] = True
    return {"ok": True}

def _preload():
    try:
        print(f"[preload] 음성 인식 모델({WHISPER_MODEL}) 준비 중… 처음이면 약 {MODEL_SIZE.get(WHISPER_MODEL, '수백')}MB를 내려받아요.")
        load_whisper()
        load_encoder() if not HF_TOKEN else load_pyannote()
        print("[preload] 준비 완료. 이제 MeetNote에서 분석을 시작하세요.")
    except Exception as e:
        print("[preload] 미리 불러오기 실패(분석 요청 시 다시 시도):", e)

@app.get("/health")
def health():
    return {"ok": True, "whisper": WHISPER_MODEL, "ready": _whisper is not None,
            "diarizer": "pyannote" if HF_TOKEN else ("resemblyzer" if _encoder else "none"), "ffmpeg": bool(shutil.which("ffmpeg"))}

# ---- 웹 앱을 같은 주소에서 제공 (exe/도커 배포용) ----
if WEB_DIR:
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    @app.get("/", include_in_schema=False)
    def _index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))
    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")

if __name__ == "__main__":
    import uvicorn
    print(f"MeetNote 발언자 구분 서비스: http://localhost:{PORT}  (whisper={WHISPER_MODEL}, HF_TOKEN={'설정됨' if HF_TOKEN else '없음 → 경량 군집 사용'})")
    if not shutil.which("ffmpeg"):
        print("[경고] ffmpeg가 없어요. 분석이 실패합니다. Windows: winget install ffmpeg / macOS: brew install ffmpeg")
    if PRELOAD:
        threading.Thread(target=_preload, daemon=True).start()
    if WEB_DIR and os.environ.get("OPEN_BROWSER", "1") != "0":
        print(f"[web] MeetNote 앱: http://localhost:{PORT}/")
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}/")).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
