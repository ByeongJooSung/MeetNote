#!/usr/bin/env python3
"""브라우저 내장 분석(전사 + 발언자 구분) 정확도 평가. 실제 회의 녹음과 정답 전사로 점수를 매긴다.

준비: 녹음 파일과 같은 이름의 정답 전사(.txt)를 한 폴더에 둔다(폴더 tests/eval_data/ 는 git에 올라가지 않는다).
  tests/eval_data/회의1.m4a  +  tests/eval_data/회의1.txt
  정답 전사는 클로바노트 '음성 기록' 내보내기(시간 기록 포함)를 그대로 쓰고, 틀린 글자·발언자만 고치면 된다.
  (형식: 빈 줄로 나뉜 묶음마다 첫 줄 "참석자 1 00:05", 다음 줄부터 발언. 앱의 전사 파일 가져오기와 같은 해석기를 쓴다)

실행:
  python tests/eval_stt.py tests/eval_data                       # 폴더 안 모든 짝, 기본 모델 등급(auto)
  python tests/eval_stt.py tests/eval_data --tier balanced --compare   # 발언자 구분 새 방식(window)과 예전 방식(long)을 같은 전사로 비교
  python tests/eval_stt.py 회의1.m4a 회의1.txt --tier fast --n 4       # 파일 하나, 발언자 수 지정
  python tests/eval_stt.py tests/eval_data --gpu                   # 설치된 Edge/Chrome 창을 띄워 WebGPU로(내장 그래픽 포함)
결과: 화면에 표 + tests/eval_out/ 에 JSON(점수·설정)과 결과 전사(.txt)를 남긴다. 버전·설정별로 모아 두고 비교한다.

점수(낮을수록 좋음, 정확도는 높을수록 좋음):
  CER      글자 오류율. 띄어쓰기·문장부호를 빼고 비교(숫자 표기 차이 '10%' vs '십 퍼센트'도 오류로 잡히니 절대값보다 비교용)
  cpCER    발언자까지 맞춰야 하는 글자 오류율. 화자별로 글을 모아 비교 → cpCER - CER 이 발언자 구분 때문에 생긴 오류
  화자정확 말하는 시간 중 결과의 발언자가 정답과 같은 비율(결과·정답 번호는 가장 많이 겹치는 1:1로 대응)
  화자수   결과 / 정답
"""
import argparse, asyncio, datetime, json, os, re, sys, time, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

AUDIO_EXT = ('.m4a', '.mp3', '.wav', '.webm', '.ogg', '.mp4', '.aac', '.flac')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eval_out')

# ---------- 점수 ----------
def norm(s):
    s = unicodedata.normalize('NFC', s or '').lower()
    return ''.join(ch for ch in s if ch.isalnum())

def lev(a, b):
    """편집 거리(글자). rapidfuzz가 있으면 그것을, 없으면 파이썬 DP."""
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(a, b)
    except ImportError:
        pass
    if len(a) < len(b): a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]

def speaker_map(ref, hyp, step=0.1):
    """시간을 0.1초씩 훑어 (정답 화자, 결과 화자) 겹침을 세고, 큰 것부터 1:1 대응. 반환: 대응표, 화자정확, 결과 없음 비율"""
    if not ref or not hyp: return {}, None, None
    end = max(max(s['t1'] for s in ref), max(s['t1'] for s in hyp))
    def at(segs):
        out = [None] * (int(end / step) + 2)
        for s in segs:
            for k in range(int(s['t0'] / step), min(len(out), int(s['t1'] / step) + 1)):
                if out[k] is None: out[k] = s['spk']
        return out
    R, H = at(ref), at(hyp)
    pairs, both, missed, spoken = {}, 0, 0, 0
    for r, h in zip(R, H):
        if r is None: continue
        spoken += 1
        if h is None: missed += 1; continue
        both += 1; pairs[(r, h)] = pairs.get((r, h), 0) + 1
    m, ur, uh, ok = {}, set(), set(), 0
    for (r, h), n in sorted(pairs.items(), key=lambda x: -x[1]):
        if r in ur or h in uh: continue
        ur.add(r); uh.add(h); m[h] = r; ok += n
    return m, (ok / both if both else None), (missed / spoken if spoken else None)

def cp_cer(ref, hyp, mapping):
    """화자별로 글을 이어 붙여 대응된 화자끼리 비교. 대응 없는 결과 화자의 글은 전부 삽입 오류"""
    rt, ht = {}, {}
    for s in ref: rt[s['spk']] = rt.get(s['spk'], '') + norm(s['text'])
    for s in hyp: ht[s['spk']] = ht.get(s['spk'], '') + norm(s['text'])
    total = sum(len(v) for v in rt.values()) or 1
    inv = {r: h for h, r in mapping.items()}
    err = sum(lev(txt, ht.get(inv.get(r), '')) for r, txt in rt.items())
    err += sum(len(txt) for h, txt in ht.items() if h not in mapping)
    return err / total

def score(ref, hyp, timed):
    r_all, h_all = norm(''.join(s['text'] for s in ref)), norm(''.join(s['text'] for s in hyp))
    out = {'cer': lev(r_all, h_all) / (len(r_all) or 1), 'ref_chars': len(r_all), 'hyp_chars': len(h_all),
           'ref_speakers': len({s['spk'] for s in ref}), 'hyp_speakers': len({s['spk'] for s in hyp})}
    if timed:
        m, acc, missed = speaker_map(ref, hyp)
        out.update({'speaker_acc': acc, 'missed_speech': missed, 'cpcer': cp_cer(ref, hyp, m), 'mapping': m})
    return out

def read_text(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949'):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode('utf-8', errors='replace')

def find_pairs(args):
    pairs = []
    if len(args) == 2 and os.path.isfile(args[0]) and args[1].lower().endswith('.txt'):
        return [(args[0], args[1])]
    for d in args:
        if not os.path.isdir(d): raise SystemExit(f'폴더나 "녹음 정답.txt" 짝을 주세요: {d}')
        for f in sorted(os.listdir(d)):
            base, ext = os.path.splitext(f)
            if ext.lower() in AUDIO_EXT and os.path.isfile(os.path.join(d, base + '.txt')):
                pairs.append((os.path.join(d, f), os.path.join(d, base + '.txt')))
    if not pairs: raise SystemExit('녹음과 같은 이름의 .txt 정답 전사를 찾지 못했어요.')
    return pairs

# ---------- 앱 실행 ----------
async def open_app(p, url, gpu):
    if gpu:
        b = None
        for ch in ('msedge', 'chrome'):
            try: b = await p.chromium.launch(channel=ch, headless=False, args=['--enable-unsafe-webgpu']); break
            except Exception: pass
        if b is None: raise SystemExit('--gpu 는 설치된 Edge나 Chrome이 필요해요.')
    else:
        b = await p.chromium.launch()
    ctx = await b.new_context(service_workers='block'); await ctx.add_init_script(smoke.NO_LOGIN)
    return b, ctx

async def run_one(p, url, audio, ref_path, a):
    b, ctx = await open_app(p, url, a.gpu)
    pg = await ctx.new_page(); logs, errs = [], []
    pg.on('console', lambda m: logs.append(m.text))
    pg.on('pageerror', lambda e: errs.append(str(e)))
    await pg.goto(url); await pg.wait_for_timeout(1500)
    if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
    await pg.wait_for_timeout(700)
    if await pg.locator('#dashPage').is_visible(): await pg.click('#dashNew'); await pg.wait_for_timeout(300)   # 대시보드 → 새 회의록
    ref = await pg.evaluate('t => __meetnote.parseTranscriptText(t)', read_text(ref_path))
    ref_segs = [{'t0': s.get('t0', 0), 't1': s.get('t1', 0), 'spk': s.get('spk') or '?', 'text': s['text']} for s in ref['segs']]
    if not ref_segs: raise SystemExit(f'정답 전사를 읽지 못했어요: {ref_path}')
    await pg.set_input_files('#audioInput', audio); await pg.wait_for_timeout(1500)
    if await pg.locator('#analyzeDlg').is_visible(): await pg.click('#anaSkip')
    await pg.evaluate("([t, n, l]) => { Object.assign(__meetnote.diarState(), { mode: 'browser', tier: t, n, algo: 'window' }); document.querySelector('#lang').value = l; }", [a.tier, a.n, a.lang])
    t0 = time.time()
    res = await pg.evaluate("__meetnote.diarizeBrowser({ title: 'eval' }).then(ok => ({ ok, segs: __meetnote.S.segments.map(g => ({ t0: g.t0, t1: g.t1, spk: g.spk, text: g.text })), dur: __meetnote.S.duration })).catch(e => ({ err: String(e && e.message || e) }))")
    secs = time.time() - t0
    if res.get('err'): raise SystemExit(f'분석 실패: {res["err"]}\n' + '\n'.join(logs[-15:]))
    runs = [('window', res['segs'], secs)]
    if a.compare:   # 같은 전사(단어)에 예전 방식 발언자 구분만 다시
        t1 = time.time()
        old = await pg.evaluate("""async () => { const d = __meetnote.diarState(), w = __meetnote.lastWords(); d.algo = 'long';
          try { const r = await __meetnote.browserSpeakersFor(w, null, () => {}); const raw = r.segments.map(s => ({ t0: +s.t0, t1: +s.t1, text: String(s.text || '').trim(), spk: String(s.spk) })).filter(s => s.text);
            return __meetnote.mergeSegments(__meetnote.cleanSegments(raw)).map(g => ({ t0: g.t0, t1: g.t1, spk: g.spk, text: g.text })); } finally { d.algo = 'window'; } }""")
        runs.append(('long', old, time.time() - t1))
    dev = next((l for l in logs if '내장 발언자 구분 시작' in l), '')
    info = [l for l in logs if '화자 통일' in l or '인식 구간' in l or 'GPU' in l]
    await b.close()
    return ref, ref_segs, runs, res.get('dur') or 0, dev, info, errs

def pct(x): return '-' if x is None else f'{x * 100:5.1f}%'

async def main():
    ap = argparse.ArgumentParser(description='브라우저 내장 분석 정확도 평가')
    ap.add_argument('paths', nargs='+'); ap.add_argument('--tier', default='auto', choices=['auto', 'fast', 'balanced', 'accurate'])
    ap.add_argument('--n', type=int, default=0, help='발언자 수(0=자동)'); ap.add_argument('--lang', default='ko-KR')
    ap.add_argument('--compare', action='store_true', help='발언자 구분 새 방식(window)과 예전 방식(long) 비교')
    ap.add_argument('--gpu', action='store_true', help='설치된 Edge/Chrome 창으로 WebGPU 사용')
    ap.add_argument('--label', default='', help='결과 파일 이름에 붙일 메모(예: v0.32.0)')
    a = ap.parse_args()
    from playwright.async_api import async_playwright
    pairs = find_pairs(a.paths); os.makedirs(OUT_DIR, exist_ok=True)
    srv, url = smoke.serve(); rows = []
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    try:
        async with async_playwright() as p:
            for audio, ref_path in pairs:
                name = os.path.splitext(os.path.basename(audio))[0]
                print(f'▶ {name}: 분석 중 (등급 {a.tier}{", GPU" if a.gpu else ""}) — CPU에서는 녹음 길이의 몇 배가 걸릴 수 있어요', flush=True)
                ref, ref_segs, runs, dur, dev, info, errs = await run_one(p, url, audio, ref_path, a)
                for l in info: print('   ', l[:200])
                if errs: print('   페이지 오류:', errs[:3])
                for algo, segs, secs in runs:
                    sc = score(ref_segs, segs, ref.get('timed'))
                    row = {'file': name, 'algo': algo, 'tier': a.tier, 'gpu': a.gpu, 'n': a.n, 'seconds': round(secs), 'audio_sec': round(dur or 0), 'device_log': dev[:300], **sc}
                    rows.append(row)
                    base = os.path.join(OUT_DIR, f'{stamp}_{name}_{a.tier}_{algo}{"_" + a.label if a.label else ""}')
                    with open(base + '.json', 'w', encoding='utf-8') as f: json.dump({**row, 'mapping': sc.get('mapping')}, f, ensure_ascii=False, indent=1)
                    with open(base + '.txt', 'w', encoding='utf-8') as f:
                        mp = sc.get('mapping') or {}
                        for s in segs: f.write(f"[{int(s['t0'] // 60):02d}:{int(s['t0'] % 60):02d}] {mp.get(s['spk'], '?')}(#{s['spk']}) {s['text']}\n")
    finally:
        srv.shutdown()
    print('\n파일                 방식    CER    cpCER  화자정확 놓친말  화자수  걸린시간(녹음)')
    for r in rows:
        print(f"{r['file'][:20]:20} {r['algo']:6} {pct(r['cer'])} {pct(r.get('cpcer'))} {pct(r.get('speaker_acc'))}  {pct(r.get('missed_speech'))}  {r['hyp_speakers']}/{r['ref_speakers']}  {r['seconds']}s({r['audio_sec']}s)")
    for algo in sorted({r['algo'] for r in rows}):
        rs = [r for r in rows if r['algo'] == algo]; w = sum(r['ref_chars'] for r in rs) or 1
        avg = lambda k: None if any(r.get(k) is None for r in rs) else sum(r[k] * r['ref_chars'] for r in rs) / w
        print(f"{'평균(글자 수 가중)':18} {algo:6} {pct(avg('cer'))} {pct(avg('cpcer'))} {pct(avg('speaker_acc'))}  {pct(avg('missed_speech'))}")
    print(f'\n결과 전사·점수: {OUT_DIR}')

def self_test():
    ref = [{'t0': 0, 't1': 5, 'spk': 'A', 'text': '안녕하세요 회의를 시작합니다.'}, {'t0': 5, 't1': 9, 'spk': 'B', 'text': '네, 예산부터 보겠습니다'}]
    same = score(ref, [{'t0': 0.2, 't1': 5, 'spk': '0', 'text': '안녕하세요, 회의를 시작합니다'}, {'t0': 5.1, 't1': 9, 'spk': '1', 'text': '네 예산부터 보겠습니다.'}], True)
    swap = score(ref, [{'t0': 0, 't1': 9, 'spk': '0', 'text': '안녕하세요 회의를 시작합니다 네 예산부터 보겠습니다'}], True)
    assert same['cer'] == 0 and same['cpcer'] == 0 and same['speaker_acc'] == 1 and same['hyp_speakers'] == 2, same
    assert swap['cer'] == 0 and swap['cpcer'] > 0.3 and swap['speaker_acc'] < 0.7, swap
    assert lev('kitten', 'sitting') == 3
    print('self-test OK')

if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']: self_test()
    else: asyncio.run(main())
