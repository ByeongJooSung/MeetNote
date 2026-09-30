#!/usr/bin/env python3
"""PC 서비스 구간 병렬 처리 실측 점검 (Windows). 실행: server\\.venv\\Scripts\\python tests/server_parallel.py [반복 횟수=8]
- Windows 음성 합성(Heami 한국어)으로 문장을 만들고, 짝수 문장은 ffmpeg로 음높이를 낮춰 두 번째 목소리로 바꾼 뒤
  두 목소리가 번갈아 말하는 녹음(8회 반복이면 약 7분)을 만든다. (영어 목소리를 섞으면 Whisper가 한국어로 인식하며 영어 문장을 버려 발언자 점검이 안 된다)
- server/diarize.py의 run_pipeline을 PARALLEL=1(예전처럼 한 번에)과 PARALLEL=auto(구간 병렬)로 각각 돌려 걸린 시간, 문장 수, 발언자 수를 비교한다.
  발언자 수는 2명으로 지정한다(음높이만 바꾼 목소리는 자동 판별 기준 0.42보다 가까워 한 명으로 묶이므로).
  병렬에서도 두 목소리가 녹음 전체에서 같은 발언자 번호로 묶여야 한다(구간이 달라도 같은 사람은 같은 발언자).
"""
import json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8
TMP = os.path.join(tempfile.gettempdir(), 'meetnote_parallel')
WAV = os.path.join(TMP, f'two_voices_x{ROUNDS}.wav')
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server')
LINES = [
    '좋은 아침입니다. 오늘은 플랫폼 사업 예산을 검토하고 출시 일정을 정하겠습니다.',
    '네, 예산은 작년보다 십 퍼센트 늘리는 방향으로 검토하고 있습니다. 출시는 십이월 말이 목표입니다.',
    '좋습니다. 상세 일정은 다음 주 금요일까지 개발팀과 공유해 주세요.',
    '알겠습니다. 일정표와 견적서는 금요일까지 공유하겠습니다. 챗봇 학습은 매일 새벽에 갱신됩니다.',
    '시연 참석자도 확정하고 참고 자료를 미리 준비해 주시기 바랍니다.',
    '참석자는 공단 세 분과 안전원 두 분입니다. 참고 자료는 회의 전에 올려 두겠습니다.',
]
PS = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Heami Desktop')
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$lines = Get-Content -Encoding UTF8 '%s'
for ($i = 0; $i -lt $lines.Count; $i++) { $s.SetOutputToWaveFile((Join-Path '%s' "line$i.wav"), $fmt); $s.Speak($lines[$i]) }
$s.Dispose()
'''

def ffmpeg():
    sys.path.insert(0, SERVER)
    import shutil
    if shutil.which('ffmpeg'): return 'ffmpeg'
    import imageio_ffmpeg; return imageio_ffmpeg.get_ffmpeg_exe()

def make_wav():
    if os.path.exists(WAV) and os.path.getsize(WAV) > 100000: return
    os.makedirs(TMP, exist_ok=True)
    txt = os.path.join(TMP, 'lines.txt')
    with open(txt, 'w', encoding='utf-8-sig') as f: f.write('\n'.join(LINES))
    r = subprocess.run(['powershell', '-NoProfile', '-Command', PS % (txt, TMP)], capture_output=True, text=True)
    if r.returncode != 0: raise SystemExit('TTS 녹음을 만들지 못했어요(Windows 한국어 음성 Heami 필요): ' + r.stderr[-300:])
    clips = []
    for i in range(len(LINES)):
        src = os.path.join(TMP, f'line{i}.wav')
        if i % 2:   # 두 번째 목소리: 음높이를 낮추고 빠르기는 그대로
            dst = os.path.join(TMP, f'line{i}_b.wav')
            subprocess.run([ffmpeg(), '-y', '-i', src, '-af', 'asetrate=16000*0.78,aresample=16000,atempo=1.282', dst], capture_output=True, check=True); src = dst
        clips.append(sf.read(src, dtype='float32')[0])
    gap = np.zeros(int(16000 * 0.7), dtype='float32')
    sf.write(WAV, np.concatenate([x for _ in range(ROUNDS) for c in clips for x in (c, gap)]), 16000)

CHILD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[2])
import diarize
t = time.time(); diarize.load_whisper(); diarize.load_encoder(); load = time.time() - t
t = time.time(); res = diarize.run_pipeline(sys.argv[1], "ko", 2)
print("RESULT" + json.dumps({"load": load, "run": time.time() - t, "workers": diarize.WORKERS, "diarizer": res["diarizer"],
      "segs": [[s["spk"], s["t0"], s["t1"], s["text"]] for s in res["segments"]]}, ensure_ascii=False))
'''

def run(parallel):
    env = {**os.environ, 'PARALLEL': parallel, 'PRELOAD': '0', 'OPEN_BROWSER': '0', 'PYTHONIOENCODING': 'utf-8'}
    r = subprocess.run([sys.executable, '-c', CHILD, WAV, SERVER], capture_output=True, text=True, encoding='utf-8', env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith('RESULT')), None)
    if not line: raise SystemExit(f'PARALLEL={parallel} 실패:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}')
    for l in r.stdout.splitlines():
        if l.startswith(('[whisper]', '[pipeline]', '[transcribe] 녹음', '[transcribe] 완료')): print('   ', l)
    return json.loads(line[6:])

def voice_ok(d):
    """문장 내용으로 어느 목소리인지 안다(홀수 번째 대사가 두 번째 목소리): 같은 목소리 문장은 같은 발언자, 다른 목소리는 다른 발언자여야 한다.
    (Whisper 문장 시각은 실제보다 1초쯤 어긋날 수 있어 시각으로 판별하면 경계 문장이 틀리게 채점된다)"""
    from difflib import SequenceMatcher
    norm = lambda t: ''.join(ch for ch in t if ch.isalnum())
    lines = [norm(l) for l in LINES]
    votes = {}
    for spk, _, _, text in d['segs']:
        t = norm(text)
        if len(t) < 4: continue
        score = [sum(b.size for b in SequenceMatcher(None, t, l).get_matching_blocks()) / len(t) for l in lines]
        best = max(range(len(lines)), key=score.__getitem__)
        if score[best] >= 0.7: votes.setdefault(best % 2, []).append(spk)
    top = {v: max(set(s), key=s.count) for v, s in votes.items()}
    acc = sum(s.count(top[v]) for v, s in votes.items()) / max(1, sum(len(s) for s in votes.values()))
    return len(set(top.values())) == 2, acc

def main():
    make_wav(); ok = True; out = {}
    for p in ('1', 'auto'):
        d = out[p] = run(p)
        spk = {s[0] for s in d['segs']}; chars = sum(len(s[3]) for s in d['segs'])
        sep, acc = voice_ok(d)
        print(f"PARALLEL={p}: 동시 구간 {d['workers']} · 분석 {d['run']:.1f}s (모델 로드 {d['load']:.1f}s) · 문장 {len(d['segs'])} · 글자 {chars} · 발언자 {len(spk)} ({d['diarizer']}) · 목소리 일치 {acc:.0%}")
        if not sep or acc < 0.9: ok = False; print('   두 목소리가 서로 다른 발언자로 묶이지 않았어요')
        ts = [s[1] for s in d['segs']]
        if ts != sorted(ts): ok = False; print('   문장 시각 순서가 뒤섞였어요')
    a, b = out['1'], out['auto']
    ca, cb = sum(len(s[3]) for s in a['segs']), sum(len(s[3]) for s in b['segs'])
    if abs(ca - cb) > ca * 0.1: ok = False; print(f'   병렬 전사 글자 수가 10% 넘게 달라요 ({ca} → {cb})')
    print(f"속도: {a['run'] / b['run']:.2f}배")
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': main()
