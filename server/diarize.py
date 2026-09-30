"""
MeetNote 발언자 구분 서비스 (로컬 파이썬)
- 전사: faster-whisper (기본 small, 환경변수 WHISPER_MODEL로 변경. GPU면 large-v3-turbo 권장)
- 회의 용어 사전(vocab): 클라이언트가 보낸 참석자 이름·참고 자료 용어를 hotwords/initial_prompt로 넣어 고유명사 인식 향상
- 클라우드 프록시: /cloud/clova — 네이버 클로바 스피치(브라우저에서 직접 호출 불가)를 대신 호출
- LLM 프록시: /llm/* — 휴대폰(https 앱)이 PC의 LM Studio·Ollama를 쓸 수 있게 대신 호출(LLM_BASE, 기본 http://localhost:1234)
- NVIDIA 프록시: /nim/* — NVIDIA API(build.nvidia.com, NIM_BASE)는 브라우저 직접 호출(CORS)이 막혀 여기서 대신 호출. 키는 요청 헤더로만 전달
- 발언자 구분: 1) pyannote.audio 3.1 (HF_TOKEN 있을 때, 가장 정확)
              2) resemblyzer 임베딩 + 군집 (토큰 없이, CPU)
              3) 둘 다 없으면 화자 1명으로 반환
- 병렬 처리: 녹음을 조용한 지점에서 구간으로 나눠 동시에 전사하고, 각 구간이 끝나는 대로 목소리 특징을 뽑는다.
             화자 군집은 마지막에 전체를 한 번에 해서 구간이 달라도 같은 사람은 같은 발언자가 된다(PARALLEL=1이면 예전처럼 한 번에)
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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
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
MODEL_SIZE = {"tiny": "75", "base": "145", "small": "460", "medium": "1500", "large-v3": "3000", "large-v3-turbo": "1600", "turbo": "1600", "distil-large-v3": "1500"}
CLOUD_TIMEOUT = int(os.environ.get("CLOUD_TIMEOUT", "1800"))   # 클로바 스피치 동기 인식 대기(초)
LLM_BASE = os.environ.get("LLM_BASE", "http://localhost:1234").rstrip("/")   # /llm 프록시가 대신 부를 로컬 LLM 서버(LM Studio 1234, Ollama 11434)
NIM_BASE = os.environ.get("NIM_BASE", "https://integrate.api.nvidia.com").rstrip("/")   # /nim 프록시가 대신 부를 NVIDIA API(자체 NIM 컨테이너면 그 주소)
CORES = os.cpu_count() or 4
PARALLEL = os.environ.get("PARALLEL", "auto")   # auto | 1(끄기) | 동시에 처리할 구간 수

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
WORKERS = 1   # 동시에 전사하는 구간 수(모델을 불러올 때 정해진다)

def _plan_workers(dev):
    """동시 구간 수와 구간당 CPU 스레드. CPU는 스레드를 몰아주는 것보다 구간을 나눠 돌리는 쪽이 빠르다(빔 탐색은 스레드를 잘 못 쓴다)."""
    if PARALLEL != "auto":
        try: w = max(1, min(8, int(PARALLEL)))
        except ValueError: w = 1
    else:
        w = 2 if dev == "cuda" else max(1, min(4, CORES // 4))
    threads = int(os.environ.get("CPU_THREADS", "0")) or (0 if dev == "cuda" or w == 1 else max(2, CORES // w))
    return w, threads

def _device():
    if DEVICE != "auto": return DEVICE
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0: return "cuda"
    except Exception: pass
    try:
        import torch; return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def load_whisper():
    global _whisper, WORKERS
    if _whisper is None:
        from faster_whisper import WhisperModel
        dev = _device()
        comp = COMPUTE if dev == "cpu" else ("float16" if COMPUTE == "int8" else COMPUTE)
        w, threads = _plan_workers(dev)
        try:
            _whisper = WhisperModel(WHISPER_MODEL, device=dev, compute_type=comp, cpu_threads=threads, num_workers=w)
        except Exception as e:
            if dev != "cuda" or DEVICE == "cuda": raise
            print(f"[whisper] GPU(CUDA)로 불러오지 못해 CPU로 전환: {e}")   # CUDA·cuDNN 라이브러리가 없는 PC
            dev, comp = "cpu", COMPUTE
            w, threads = _plan_workers(dev)
            _whisper = WhisperModel(WHISPER_MODEL, device=dev, compute_type=comp, cpu_threads=threads, num_workers=w)
        WORKERS = w
        print(f"[whisper] {WHISPER_MODEL} on {dev} ({comp}) · 동시 구간 {w}개{f' × 스레드 {threads}' if threads else ''}")
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

def embed_segments(wav, sr, segments, cancelled=lambda: False, on_step=None, batch=96):
    """전사 문장마다 목소리 특징(resemblyzer). 문장들의 1.6초 조각을 모아 한 번에 신경망에 넣는다(문장마다 따로 넣는 것보다 빠름).
    → [(문장, 임베딩)]. 0.6초보다 짧은 문장은 건너뛴다."""
    enc = load_encoder()
    if enc is None or not segments: return []
    import torch
    from resemblyzer import preprocess_wav, audio as rz_audio
    items = []   # (문장, [mel 조각])
    for s in segments:
        if cancelled(): raise Cancelled()
        chunk = wav[int(s["t0"] * sr):int(s["t1"] * sr)]
        if len(chunk) < sr * 0.6: continue
        try:
            w = preprocess_wav(chunk, source_sr=sr)
            if len(w) < 1600: continue
            wav_slices, mel_slices = enc.compute_partial_slices(len(w), rate=1.3, min_coverage=0.75)
            if wav_slices[-1].stop >= len(w): w = np.pad(w, (0, wav_slices[-1].stop - len(w)), "constant")
            mel = rz_audio.wav_to_mel_spectrogram(w)
            items.append((s, [mel[m] for m in mel_slices]))
        except Exception as e:
            print("[embeddings] 구간 건너뜀:", e)
    flat = [m for _, ms in items for m in ms]
    if not flat: return []
    parts = []
    with torch.no_grad():
        for i in range(0, len(flat), batch):
            if cancelled(): raise Cancelled()
            parts.append(enc(torch.from_numpy(np.stack(flat[i:i + batch])).to(enc.device)).cpu().numpy())
            if on_step: on_step(min(len(flat), i + batch) / len(flat))
    P = np.concatenate(parts)
    out, k = [], 0
    for s, ms in items:
        e = P[k:k + len(ms)].mean(axis=0); k += len(ms)
        out.append((s, e / (np.linalg.norm(e) or 1.0)))
    return out

def cluster_turns(pairs, segments, num_speakers):
    """[(문장, 임베딩)] 전체를 한 번에 군집 → [(t0, t1, 화자)]."""
    if len(pairs) < 2: return [(s["t0"], s["t1"], "0") for s in segments]
    keep = [s for s, _ in pairs]
    X = np.stack([e for _, e in pairs])
    from sklearn.cluster import AgglomerativeClustering
    if num_speakers:
        cl = AgglomerativeClustering(n_clusters=min(num_speakers, len(X)), metric="cosine", linkage="average")
    else:
        cl = AgglomerativeClustering(n_clusters=None, distance_threshold=0.42, metric="cosine", linkage="average")
    labels = cl.fit_predict(X)
    return [(s["t0"], s["t1"], str(l)) for s, l in zip(keep, labels)]

class Cancelled(Exception): pass

def plan_chunks(wav, sr, workers):
    """녹음을 동시에 처리할 구간으로 나눈다 → [(시작 샘플, 끝 샘플)]. 자르는 곳은 목표 지점 ±20초 안에서 가장 조용한 0.25초라
    말이 중간에 잘리지 않는다. 구간은 동시 처리 수의 약 3배로 잘게 나눠 먼저 끝난 쪽이 다음 구간을 이어받게 한다."""
    n = len(wav); dur = n / sr
    if workers <= 1 or dur < 180: return [(0, n)]
    target = max(45.0, min(600.0, dur / (workers * 3)))
    hop = int(sr * 0.25); frames = n // hop
    rms = np.sqrt(np.mean(np.square(wav[:frames * hop].reshape(frames, hop)), axis=1) + 1e-12)
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    cuts, pos = [0], 0.0
    while dur - pos > target * 1.5:
        want = pos + target
        lo, hi = max(int((want - 20) / 0.25), int(pos / 0.25) + 1), min(int((want + 20) / 0.25), frames - 1)
        k = lo + int(np.argmin(rms[lo:hi])) if hi > lo else int(want / 0.25)
        cuts.append(k * hop + hop // 2); pos = cuts[-1] / sr
    cuts.append(n)
    return list(zip(cuts[:-1], cuts[1:]))

def _transcribe(model, audio, kw):
    try:
        return model.transcribe(audio, **kw)
    except TypeError:   # 오래된 faster-whisper: 모르는 인자는 빼고
        return model.transcribe(audio, **{k: v for k, v in kw.items() if k not in ("no_repeat_ngram_size", "repetition_penalty", "vad_parameters", "hotwords")})

def run_pipeline(src_path: str, lang: Optional[str], num_speakers: Optional[int], progress=lambda pct, stage, msg="": None, cancelled=lambda: False, vocab: Optional[str] = None):
    """전체 파이프라인. progress(pct 0~100, stage, message) 콜백으로 진행률 보고."""
    def check():
        if cancelled(): raise Cancelled()
    t_start = time.time()
    progress(8, "convert", "오디오를 16kHz로 변환하는 중")
    wav_path = to_wav(src_path); check()
    if _whisper is None:
        progress(12, "model", f"음성 인식 모델({WHISPER_MODEL})을 처음 내려받는 중 — 서버 창에 다운로드 진행률이 표시돼요 (약 {MODEL_SIZE.get(WHISPER_MODEL, '수백')}MB)")
    else:
        progress(14, "model", "음성 인식 모델 준비 중")
    model = load_whisper(); check()
    progress(16, "transcribe", "전사 준비 중 (녹음을 구간으로 나누는 중)")
    # 환청(말이 없는데 같은 단어가 반복되는 현상) 억제: VAD로 무음 제거, 앞 문장에 끌려가지 않게, 같은 구절 재생성 금지, 압축률·확률이 나쁜 구간은 버림
    kw = dict(language=(lang or None) if lang != "auto" else None, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
              beam_size=BEAM, condition_on_previous_text=False, no_repeat_ngram_size=6, repetition_penalty=1.05,
              compression_ratio_threshold=2.2, log_prob_threshold=-1.0, no_speech_threshold=0.6)
    # 회의 용어 사전(참석자 이름·참고 자료 용어): hotwords는 모든 문장에, initial_prompt는 구간마다 첫 문장에 힌트로 들어가 고유명사·약어 인식이 좋아진다
    vocab = " ".join(str(vocab or "").split())[:400]
    if vocab:
        kw["hotwords"] = vocab; kw["initial_prompt"] = vocab
        print(f"[transcribe] 용어 사전 {len(vocab)}자")
    wav, sr = read_wav(wav_path); check()
    dur = len(wav) / sr
    chunks = plan_chunks(wav, sr, WORKERS)
    par = min(WORKERS, len(chunks))
    # 발언자 구분: pyannote는 녹음 전체를 봐야 해서 전사와 동시에 따로 돌리고, resemblyzer는 구간 전사가 끝날 때마다 그 구간의 목소리 특징을 뽑는다
    use_pyannote = DIARIZER != "none" and bool(HF_TOKEN)
    embed_live = DIARIZER != "none" and not use_pyannote and load_encoder() is not None
    py_box = {}
    def _py():
        try: py_box["turns"] = diarize_pyannote(wav_path, num_speakers)
        except Exception as e: print("[pyannote] 실패:", e)
    py_thread = threading.Thread(target=_py, daemon=True) if use_pyannote else None
    if py_thread: py_thread.start()
    mm = lambda t: f"{int(t // 60):02d}:{int(t % 60):02d}"
    gpu = str(getattr(getattr(model, "model", None), "device", "")).startswith("cuda")
    lo, hi = (0.1, 0.2) if gpu else (0.5, 1.0)
    speed = 1 + 0.6 * (par - 1)   # 동시 처리로 줄어드는 시간(대략)
    est = f" · {'GPU' if gpu else 'CPU'}에서는 약 {max(1, int(dur / 60 * lo / speed))}~{max(2, int(dur / 60 * hi / speed))}분 예상" if dur else ""
    split = f" · {len(chunks)}구간으로 나눠 {par}개씩 동시 처리" if len(chunks) > 1 else ""
    progress(17, "transcribe", f"전사 시작 (녹음 {mm(dur)}{split}{est}). 첫 문장이 나오면 시간이 올라가요.")
    print(f"[transcribe] 녹음 {mm(dur)} 시작{split}{est}")

    stop = threading.Event()
    halt = lambda: cancelled() or stop.is_set()
    pos, done, lock, t_last = [0.0] * len(chunks), [0], threading.Lock(), [time.time()]
    what = "전사·목소리 특징" if embed_live else "전사"
    def report():
        with lock:
            got = sum(pos)
            tail = f" · 구간 {done[0]}/{len(chunks)} 끝남" if len(chunks) > 1 else ""
            progress(17 + (min(63, 63 * got / dur) if dur else 0), "transcribe", f"{what} 중 {mm(got)} / {mm(dur)}{tail}")
            if time.time() - t_last[0] > 10:
                t_last[0] = time.time(); print(f"[transcribe] {mm(got)} / {mm(dur)}{tail}")
    def work(ci):
        if halt(): raise Cancelled()
        a, b = chunks[ci]; off, span = a / sr, (b - a) / sr
        segs_iter, info = _transcribe(model, wav[a:b], kw)
        out = []
        for sg in segs_iter:
            if halt(): raise Cancelled()
            if sg.text.strip():
                out.append({"t0": round(off + sg.start, 2), "t1": round(off + sg.end, 2), "text": sg.text.strip()})
            pos[ci] = min(sg.end, span); report()
        pairs = embed_segments(wav, sr, out, halt) if embed_live else []
        pos[ci] = span
        with lock: done[0] += 1
        report()
        return out, getattr(info, "language", None), pairs

    if len(chunks) == 1:
        results = [work(0)]
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=par) as ex:
            futs = {ex.submit(work, i): i for i in range(len(chunks))}
            try:
                for f in as_completed(futs): results[futs[f]] = f.result()
            except BaseException:
                stop.set()   # 한 구간이 실패·취소되면 나머지도 멈춘다
                for f in futs: f.cancel()
                raise
    check()
    segments = [s for r in results for s in r[0]]
    pairs = [p for r in results for p in r[2]]
    langs = [r[1] for r in results if r[1]]
    language = max(set(langs), key=langs.count) if langs else lang
    print(f"[transcribe] 완료 {len(segments)}문장 · {time.time() - t_start:.1f}s")
    if DIARIZER == "none":
        print("[diarize] DIARIZER=none → 발언자 분석 건너뜀")
        progress(95, "finalize", "정리 중")
        return {"language": language, "duration": dur or None, "segments": [{**s, "spk": "0"} for s in segments], "diarizer": "none"}
    turns, used = None, "none"
    if py_thread:
        progress(82, "diarize", "발언자 분석(pyannote)이 끝나길 기다리는 중")
        while py_thread.is_alive():
            check(); py_thread.join(0.5)
        turns = py_box.get("turns")
        if turns: used = "pyannote"
    if turns is None:
        try:
            if not embed_live and load_encoder() is not None:   # pyannote가 실패했을 때: 지금 문장별 목소리 특징을 뽑는다
                progress(84, "diarize", "목소리 특징을 비교하는 중")
                pairs = embed_segments(wav, sr, segments, cancelled, lambda f: progress(84 + 10 * f, "diarize", f"목소리 특징 비교 {int(f * 100)}%"))
            if _encoder is not None:
                progress(94, "diarize", f"발언자를 묶는 중 ({len(pairs)}문장)")
                turns = cluster_turns(pairs, segments, num_speakers); used = "resemblyzer"
        except Cancelled:
            raise
        except Exception as e:
            print("[embeddings] 실패:", e)
    check()
    progress(95, "finalize", "정리 중")
    segments = assign_speakers(segments, turns) if turns else [{**s, "spk": "0"} for s in segments]
    print(f"[pipeline] 끝 {time.time() - t_start:.1f}s (발언자 구분: {used})")
    progress(100, "done", "완료")
    return {"language": language, "duration": dur or None, "segments": segments, "diarizer": used}

@app.post("/diarize")
async def diarize(audio: UploadFile = File(...), lang: Optional[str] = Form("ko"), num_speakers: Optional[int] = Form(None), vocab: Optional[str] = Form(None)):
    """동기 API (구버전 호환)."""
    tmpdir = tempfile.mkdtemp(prefix="meetnote_")
    try:
        src = os.path.join(tmpdir, audio.filename or "audio.bin")
        with open(src, "wb") as f: f.write(await audio.read())
        return run_pipeline(src, lang, num_speakers, vocab=vocab)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ---- 진행률을 보고하는 작업(job) API ----
JOBS = {}
JOBS_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()   # 분석은 한 번에 하나만 (CPU 경쟁 방지)

def _job_worker(job_id: str, src: str, tmpdir: str, lang, num_speakers, vocab=None):
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
        result = run_pipeline(src, lang, num_speakers, progress, lambda: job.get("cancel", False), vocab=vocab)
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
async def create_job(audio: UploadFile = File(...), lang: Optional[str] = Form("ko"), num_speakers: Optional[int] = Form(None), vocab: Optional[str] = Form(None)):
    _gc_jobs()
    tmpdir = tempfile.mkdtemp(prefix="meetnote_")
    src = os.path.join(tmpdir, audio.filename or "audio.bin")
    with open(src, "wb") as f: f.write(await audio.read())
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"id": job_id, "state": "queued", "pct": 3, "stage": "queued", "message": "대기 중", "created": time.time()}
    threading.Thread(target=_job_worker, args=(job_id, src, tmpdir, lang, num_speakers, vocab), daemon=True).start()
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

# ---- 클라우드 STT 프록시: 네이버 클로바 스피치(장문 인식)는 브라우저에서 직접 부를 수 없어(CORS) 여기서 대신 보낸다 ----
# 키·Invoke URL은 요청마다 받아 전달만 하고 저장하지 않는다. 서버 환경변수 CLOVA_SPEECH_URL / CLOVA_SPEECH_KEY 가 있으면 그것을 기본값으로 쓴다.
@app.post("/cloud/clova")
async def cloud_clova(audio: UploadFile = File(...), invoke_url: Optional[str] = Form(None), key: Optional[str] = Form(None), lang: Optional[str] = Form("ko-KR"),
                      num_speakers: Optional[int] = Form(None), vocab: Optional[str] = Form(None)):
    import json, requests
    url = (invoke_url or os.environ.get("CLOVA_SPEECH_URL", "")).strip().rstrip("/")
    secret = (key or os.environ.get("CLOVA_SPEECH_KEY", "")).strip()
    if not url.startswith("http") or not secret:
        raise HTTPException(400, "클로바 스피치 Invoke URL과 Secret Key가 필요해요.")
    if not url.endswith("/recognizer/upload"): url += "/recognizer/upload"
    params = {"language": lang or "ko-KR", "completion": "sync", "wordAlignment": False, "fullText": False, "noiseFiltering": True,
              "diarization": {"enable": True, **({"speakerCountMin": num_speakers, "speakerCountMax": num_speakers} if num_speakers else {})}}
    words = [w.strip() for w in str(vocab or "").split(",") if w.strip()][:100]
    if words: params["boostings"] = [{"words": ", ".join(words), "weight": "3"}]
    data = await audio.read()
    print(f"[cloud/clova] {len(data) // 1024}KB lang={params['language']} speakers={num_speakers or 'auto'} vocab={len(words)}")
    try:
        r = requests.post(url, headers={"X-CLOVASPEECH-API-KEY": secret, "Accept": "application/json"},
                          files={"media": (audio.filename or "audio.bin", data)}, data={"params": json.dumps(params, ensure_ascii=False)}, timeout=CLOUD_TIMEOUT)
    except requests.RequestException as e:
        raise HTTPException(502, f"클로바 스피치에 연결하지 못했어요: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"클로바 스피치 오류(HTTP {r.status_code}): {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        raise HTTPException(502, "클로바 스피치 응답을 해석하지 못했어요: " + r.text[:200])

# ---- 로컬 LLM 프록시: 휴대폰(https 앱)은 http LAN 주소를 부를 수 없어(혼합 콘텐츠) 이 서버가 LM Studio·Ollama를 대신 부른다 ----
# 앱의 AI 서버 주소를 "<이 서버의 https 터널>/llm"으로 두면 /llm/v1/chat/completions 등이 LLM_BASE로 그대로 전달된다(스트리밍 포함)
async def _forward(base: str, path: str, request: Request, fail: str):
    import requests
    from starlette.concurrency import run_in_threadpool
    url = f"{base}/{path}" + (f"?{request.url.query}" if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "authorization", "accept")}
    body = await request.body()
    try:
        r = await run_in_threadpool(lambda: requests.request(request.method, url, headers=headers, data=body or None, stream=True, timeout=(10, 3600)))
    except requests.RequestException as e:
        raise HTTPException(502, f"{fail}: {e}")
    ct = r.headers.get("content-type", "application/json")
    if "text/event-stream" in ct:
        return StreamingResponse(r.iter_content(chunk_size=None), status_code=r.status_code, media_type=ct, headers={"cache-control": "no-cache", "x-accel-buffering": "no"})
    content = r.content; r.close()
    return Response(content=content, status_code=r.status_code, media_type=ct)

@app.api_route("/llm/{path:path}", methods=["GET", "POST"])
async def llm_proxy(path: str, request: Request):
    return await _forward(LLM_BASE, path, request, f"LLM 서버({LLM_BASE})에 연결하지 못했어요. LM Studio 서버가 켜져 있는지, LLM_BASE 환경변수가 맞는지 확인하세요")

# ---- NVIDIA API 프록시: integrate.api.nvidia.com은 브라우저 호출(CORS)을 막아 이 서버가 대신 부른다. 앱의 서버 주소 "<PC 서비스>/nim" → NIM_BASE ----
# API 키(nvapi-…)는 요청의 Authorization 헤더로 그대로 전달만 하고 저장·기록하지 않는다
@app.api_route("/nim/{path:path}", methods=["GET", "POST"])
async def nim_proxy(path: str, request: Request):
    return await _forward(NIM_BASE, path, request, f"NVIDIA API({NIM_BASE})에 연결하지 못했어요. 인터넷 연결과 NIM_BASE 환경변수를 확인하세요")

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
    return {"ok": True, "whisper": WHISPER_MODEL, "ready": _whisper is not None, "cloud": ["clova"], "vocab": True, "llm": LLM_BASE, "nim": True, "parallel": WORKERS,
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
