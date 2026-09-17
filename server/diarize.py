"""
MeetNote 발언자 구분 서비스 (로컬 파이썬)
- 전사: faster-whisper (기본 small, 환경변수 WHISPER_MODEL로 변경)
- 발언자 구분: 1) pyannote.audio 3.1 (HF_TOKEN 있을 때, 가장 정확)
              2) resemblyzer 임베딩 + 군집 (토큰 없이, CPU)
              3) 둘 다 없으면 화자 1명으로 반환
실행: pip install -r requirements.txt && python diarize.py   (http://localhost:8765)
"""
import os, io, tempfile, subprocess, shutil, json, math, threading, time, uuid
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
DEVICE = os.environ.get("DEVICE", "auto")          # auto | cpu | cuda
COMPUTE = os.environ.get("COMPUTE", "int8")         # int8 (CPU) | float16 (GPU)
HF_TOKEN = os.environ.get("HF_TOKEN", "")
PORT = int(os.environ.get("PORT", "8765"))
PRELOAD = os.environ.get("PRELOAD", "1") != "0"   # 시작 시 모델을 미리 내려받아 첫 분석을 빠르게
MODEL_SIZE = {"tiny": "75", "base": "145", "small": "460", "medium": "1500", "large-v3": "3000"}

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
    if _encoder is None:
        try:
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

def diarize_embeddings(wav, sr, segments, num_speakers):
    enc = load_encoder()
    if enc is None or not segments: return None
    from resemblyzer import preprocess_wav
    embs, keep = [], []
    for s in segments:
        a, b = int(s["t0"] * sr), int(s["t1"] * sr)
        chunk = wav[a:b]
        if len(chunk) < sr * 0.6: continue
        try:
            embs.append(enc.embed_utterance(preprocess_wav(chunk, source_sr=sr)))
            keep.append(s)
        except Exception:
            continue
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
    progress(16, "transcribe", "전사 중")
    segs_iter, info = model.transcribe(wav_path, language=(lang or None) if lang != "auto" else None, vad_filter=True, beam_size=5)
    dur = float(getattr(info, "duration", 0) or 0)
    segments = []
    for sg in segs_iter:
        check()
        if sg.text.strip():
            segments.append({"t0": round(sg.start, 2), "t1": round(sg.end, 2), "text": sg.text.strip()})
        if dur > 0:
            progress(16 + min(54, 54 * sg.end / dur), "transcribe", f"전사 중 {int(sg.end // 60):02d}:{int(sg.end % 60):02d} / {int(dur // 60):02d}:{int(dur % 60):02d}")
    progress(72, "diarize", "발언자 분석 중"); check()
    turns = None
    try:
        turns = diarize_pyannote(wav_path, num_speakers)
    except Exception as e:
        print("[pyannote] 실패:", e)
    check()
    if turns is None:
        try:
            wav, sr = read_wav(wav_path)
            progress(80, "diarize", "목소리 특징을 비교하는 중")
            turns = diarize_embeddings(wav, sr, segments, num_speakers)
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

def _job_worker(job_id: str, src: str, tmpdir: str, lang, num_speakers):
    job = JOBS[job_id]
    def progress(pct, stage, msg=""):
        job.update({"pct": round(float(pct), 1), "stage": stage, "message": msg, "updated": time.time()})
    try:
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

if __name__ == "__main__":
    import uvicorn
    print(f"MeetNote 발언자 구분 서비스: http://localhost:{PORT}  (whisper={WHISPER_MODEL}, HF_TOKEN={'설정됨' if HF_TOKEN else '없음 → 경량 군집 사용'})")
    if not shutil.which("ffmpeg"):
        print("[경고] ffmpeg가 없어요. 분석이 실패합니다. Windows: winget install ffmpeg / macOS: brew install ffmpeg")
    if PRELOAD:
        threading.Thread(target=_preload, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
