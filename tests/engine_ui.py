#!/usr/bin/env python3
"""앱에서 PC 서비스 전사 엔진 고르기 점검 (Playwright + 실제 PC 서비스). 실행: python tests/engine_ui.py
- 먼저 PC 서비스를 켜 두세요(server: python diarize.py, http://localhost:8765). qwen-asr이 설치돼 있어야 Qwen3 단계가 돈다.
① 발언자 구분 창에 전사 엔진 선택이 있고 고른 값이 기억된다 ② Whisper로 분석 → 결과에 엔진 표시
③ Qwen3-ASR 0.6B로 다시 분석 → "이전 전사 받아 두고 바꾸기"로 이전 결과(.txt)를 내려받고 바뀐다 ④ .mnote에 엔진이 저장된다
녹음은 server_parallel.py의 두 목소리 TTS 1회분(약 50초)을 쓴다.
"""
import asyncio, json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

def tts_wav():   # 녹음 만들기는 numpy·soundfile이 있는 PC 서비스 가상환경 파이썬에 맡긴다(Playwright는 이 파이썬)
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(here, '..', 'server', '.venv', 'Scripts' if os.name == 'nt' else 'bin', 'python')
    code = "import sys; sys.argv=['x','1']; sys.path.insert(0, r'%s'); import os, server_parallel as sp; sp.ROUNDS=1; sp.WAV=os.path.join(sp.TMP,'two_voices_x1.wav'); sp.make_wav(); print(sp.WAV)" % here
    r = subprocess.run([py if os.path.exists(py + ('.exe' if os.name == 'nt' else '')) else sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace')
    path = (r.stdout.strip().splitlines() or [''])[-1]
    if not os.path.exists(path): raise SystemExit('TTS 녹음을 만들지 못했어요: ' + r.stderr[-400:])
    return path

async def run():
    from playwright.async_api import async_playwright
    try: h = json.load(urllib.request.urlopen('http://localhost:8765/health', timeout=5))
    except Exception: raise SystemExit('PC 서비스(http://localhost:8765)가 꺼져 있어요. server 폴더에서 python diarize.py로 켠 뒤 다시 실행하세요.')
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    wav = tts_wav(); srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block', accept_downloads=True)
        await ctx.add_init_script(smoke.NO_LOGIN)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        await pg.set_input_files('#audioInput', wav); await pg.wait_for_timeout(1500)
        if await pg.locator('#analyzeDlg').is_visible(): await pg.click('#anaSkip')
        await pg.click('#tabTr')
        async def analyze(engine):
            if await pg.locator('#mapDlg').is_visible(): await pg.keyboard.press('Escape'); await pg.wait_for_timeout(300)   # 분석 뒤 자동으로 뜨는 참석자 매핑 창
            await pg.click('#diarBtn'); await pg.wait_for_timeout(300)
            await pg.check('input[name="diarMode"][value="py"]'); await pg.fill('#diarBase', 'http://localhost:8765'); await pg.dispatch_event('#diarBase', 'change')
            await pg.fill('#diarN', '2'); await pg.dispatch_event('#diarN', 'change')
            await pg.select_option('#diarAsr', engine); await pg.wait_for_timeout(200)
            note = await pg.text_content('#diarAsrNote')
            await pg.click('#diarGo')
            return note
        note = await analyze('whisper')
        expect(note == '', 'Whisper는 안내 없음')
        for _ in range(240):
            await pg.wait_for_timeout(500)
            if await pg.evaluate("__meetnote.S.segments.length > 0") and not await pg.locator('#progDlg').is_visible(): break
        e1 = await pg.evaluate("__meetnote.S.trEngine")
        expect(e1.startswith('Whisper') and await pg.evaluate("__meetnote.S.segments.length") > 3, f'Whisper 분석 결과·엔진 기록 {e1}')
        note = await analyze('qwen3-0.6b')
        expect('시험용 엔진' in note, 'Qwen3 고르면 안내')
        expect(await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.diar')).asr") == 'qwen3-0.6b', '고른 엔진을 기억')
        for _ in range(900):
            await pg.wait_for_timeout(500)
            if await pg.locator('#choiceDlg').is_visible(): break
        expect(await pg.locator('#choiceDlg').is_visible() and 'Whisper' in await pg.text_content('#choiceMsg') and 'Qwen3' in await pg.text_content('#choiceMsg'), '바꾸기 전에 두 엔진 이름과 함께 물음')
        async with pg.expect_download() as dl:
            await pg.click('[data-choice="save"]')
        d = await dl.value; path = await d.path(); txt = open(path, encoding='utf-8').read()
        expect(d.suggested_filename.endswith('.txt') and txt.startswith('전사 엔진: Whisper') and '[00:' in txt, f'이전 전사(.txt) 내려받기 {d.suggested_filename}')
        await pg.wait_for_timeout(500)
        e2 = await pg.evaluate("__meetnote.S.trEngine")
        expect(e2 == 'Qwen3-ASR 0.6B' and await pg.evaluate("__meetnote.S.segments.length") > 3, f'Qwen3 결과로 바뀜 {e2}')
        spk = await pg.evaluate("[...new Set(__meetnote.S.segments.map(g => g.spk))].length")
        expect(spk == 2, f'발언자 2명 {spk}')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
