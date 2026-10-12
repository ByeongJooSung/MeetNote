#!/usr/bin/env python3
"""PC 서비스 전사 엔진 비교 (Whisper ↔ Qwen3-ASR). 실행: server\\.venv\\Scripts\\python tests/server_engines.py [녹음 파일] [엔진들]
- 녹음 파일을 주지 않으면 server_parallel.py의 두 목소리 TTS 녹음(3회 반복, 약 2분 30초)을 만들어 쓴다.
- 엔진: whisper,qwen3-0.6b (기본) · qwen3-1.7b도 가능. 같은 녹음을 엔진마다 run_pipeline으로 돌려 걸린 시간·문장 수·발언자 수와
  앞부분 전사를 나란히 보여 주고, 결과 전체를 tests 폴더 밖 임시 폴더에 엔진별 .txt로 남긴다(직접 비교용).
- TTS 녹음이면 대본과 비교한 글자 일치율(%)도 낸다.
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server')
CHILD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[2])
import diarize
t = time.time(); res = diarize.run_pipeline(sys.argv[1], "ko", 2 if sys.argv[4] == "1" else None, engine=sys.argv[3])
print("RESULT" + json.dumps({"run": time.time() - t, "engine": res.get("engine"), "diarizer": res["diarizer"], "segs": [[s["spk"], s["t0"], s["t1"], s["text"]] for s in res["segments"]]}, ensure_ascii=False))
'''

def run(wav, engine, two):
    env = {**os.environ, 'PRELOAD': '0', 'OPEN_BROWSER': '0', 'PYTHONIOENCODING': 'utf-8'}
    r = subprocess.run([sys.executable, '-c', CHILD, wav, SERVER, engine, '1' if two else '0'], capture_output=True, text=True, encoding='utf-8', env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith('RESULT')), None)
    if not line: raise SystemExit(f'{engine} 실패:\n{r.stdout[-1500:]}\n{r.stderr[-2500:]}')
    return json.loads(line[6:])

def similarity(ref, hyp):   # 1 - 글자 오류율(CER, 편집 거리 ÷ 대본 글자 수). 숫자 표기(십/10)·띄어쓰기·문장부호 차이는 빼고 비교
    import re
    num = {'십 퍼센트': '10%', '십이월': '12월', '세 분': '3분', '두 분': '2분'}
    def norm(t):
        for k, v in num.items(): t = t.replace(k, v)
        return re.sub(r'[^\w%]', '', t)
    a, b = norm(ref), norm(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1): cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return max(0.0, 1 - prev[-1] / max(1, len(a)))

def main():
    args = [a for a in sys.argv[1:]]
    wav = args[0] if args and os.path.exists(args[0]) else None
    engines = (args[1] if wav and len(args) > 1 else args[0] if args and not wav else 'whisper,qwen3-0.6b').split(',')
    ref = None
    if not wav:
        sys.argv = [sys.argv[0], '3']
        import server_parallel as sp
        sp.ROUNDS = 3; sp.WAV = os.path.join(sp.TMP, 'two_voices_x3.wav'); sp.make_wav(); wav = sp.WAV
        ref = ' '.join(sp.LINES * 3)
    out_dir = os.path.join(tempfile.gettempdir(), 'meetnote_engines'); os.makedirs(out_dir, exist_ok=True)
    rows = []
    for e in engines:
        d = run(wav, e.strip(), two=ref is not None)
        text = ' '.join(s[3] for s in d['segs'])
        path = os.path.join(out_dir, f'{e.strip()}.txt')
        with open(path, 'w', encoding='utf-8') as f: f.write('\n'.join(f"[{int(s[1]//60):02d}:{int(s[1]%60):02d}] {s[0]}: {s[3]}" for s in d['segs']))
        acc = f" · 대본 일치 {similarity(ref, text):.1%}" if ref else ''
        print(f"{d['engine']}: {d['run']:.1f}s · 문장 {len(d['segs'])} · 글자 {len(text)} · 발언자 {len({s[0] for s in d['segs']})} ({d['diarizer']}){acc}")
        for s in d['segs'][:4]: print(f"    [{s[1]:6.1f}–{s[2]:6.1f}] {s[0]}: {s[3][:70]}")
        print(f"    전체: {path}")
        rows.append(d)
    ok = all(r['segs'] and all(r['segs'][i][1] <= r['segs'][i + 1][1] for i in range(len(r['segs']) - 1)) for r in rows)
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': main()
