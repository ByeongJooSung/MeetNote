#!/usr/bin/env python3
"""브라우저 내장 발언자 구분 실측 점검 (Windows). 실행: python tests/diar_two_voices.py [fast|balanced|accurate]
- Windows 음성 합성(Zira 영어 + Heami 한국어)으로 두 목소리가 번갈아 말하는 50초 녹음을 만든 뒤
  브라우저 내장 분석(CPU/wasm)을 돌려 화자가 2명으로 묶이는지 본다. 모델은 처음 한 번 내려받는다(fast 약 120MB).
- 임베딩·군집 기준(unifySpeakers)을 바꿨을 때 반드시 돌려 볼 것. 헤드리스 Chromium에는 WebGPU가 없어 accurate는 균형으로 내려간다.
"""
import asyncio, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke
WAV = os.path.join(tempfile.gettempdir(), 'meetnote_two_voices.wav')
TIER = sys.argv[1] if len(sys.argv) > 1 else 'fast'
PS = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('%s', $fmt)
$pb = New-Object System.Speech.Synthesis.PromptBuilder
$lines = @(
 @('Microsoft Zira Desktop','Good morning everyone. Today we will review the budget for the platform project and decide the release date.'),
 @('Microsoft Heami Desktop','네, 예산은 작년보다 십 퍼센트 늘리는 방향으로 검토하고 있습니다. 출시는 십이월 말이 목표입니다.'),
 @('Microsoft Zira Desktop','That sounds reasonable. Please share the detailed schedule with the engineering team by next Friday.'),
 @('Microsoft Heami Desktop','알겠습니다. 일정표와 견적서는 금요일까지 공유하겠습니다. 그리고 챗봇 학습은 매일 새벽에 갱신됩니다.'),
 @('Microsoft Zira Desktop','Great. Let us also confirm the attendees for the demonstration and prepare the reference documents.'),
 @('Microsoft Heami Desktop','참석자는 공단 세 분과 안전원 두 분입니다. 참고 자료는 회의 전에 올려 두겠습니다.')
)
foreach ($l in $lines) { $pb.StartVoice($l[0]); $pb.AppendText($l[1]); $pb.EndVoice(); $pb.AppendBreak([TimeSpan]::FromMilliseconds(700)) }
$s.Speak($pb); $s.Dispose()
'''

def make_wav():
    if os.path.exists(WAV) and os.path.getsize(WAV) > 100000: return
    r = subprocess.run(['powershell', '-NoProfile', '-Command', PS % WAV], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(WAV): raise SystemExit('TTS 녹음을 만들지 못했어요(Windows 음성 Zira·Heami 필요): ' + r.stderr[-300:])

async def run():
    from playwright.async_api import async_playwright
    make_wav(); srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(service_workers='block'); pg = await ctx.new_page()
        await ctx.add_init_script(smoke.NO_LOGIN)
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        logs = []; pg.on('console', lambda m: logs.append(m.text) if 'MeetNote' in m.text else None)
        await pg.goto(url); await pg.wait_for_timeout(1500)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700)
        if await pg.locator('#cloudDlg').is_visible(): await pg.click('#cloudClose')
        await pg.set_input_files('#audioInput', WAV); await pg.wait_for_timeout(1500)
        if await pg.locator('#analyzeDlg').is_visible(): await pg.click('#anaSkip')
        await pg.evaluate("Object.assign(__meetnote.diarState(), { mode: 'browser', tier: '%s', n: 0 })" % TIER)
        await pg.evaluate("document.querySelector('#lang').value = 'en-US'")
        t0 = time.time()
        res = await pg.evaluate("__meetnote.diarizeBrowser({ title: 't' }).then(ok => ({ ok, segs: __meetnote.S.segments.map(g => [g.spk, Math.round(g.t0), Math.round(g.t1), g.text.slice(0, 40)]) })).catch(e => ({ err: String(e && e.message || e) }))")
        print(f'{TIER}: {round(time.time() - t0)}s'); print(res)
        for l in logs:
            if '화자 통일' in l or '거리' in l or '실패' in l or '오류' in l or '인식 구간' in l: print(l)
        n = len({g[0] for g in res.get('segs', [])})
        print('RESULT:', 'OK' if n == 2 and not errs else f'FAIL (speakers={n}, errors={errs[:2]})')
        await b.close()
    srv.shutdown()

if __name__ == '__main__': asyncio.run(run())
