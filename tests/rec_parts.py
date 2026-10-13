#!/usr/bin/env python3
"""녹음 나누기(1부·2부·3부)와 녹음 파일 내려받기 점검 (Playwright, Chromium 가짜 마이크). 실행: python tests/rec_parts.py
① 녹음 → 2부 시작 → 일시정지 → 3부 시작(이어서 녹음) → 정지: S.parts 3개, 부별 녹음 파일 3개
② 타임라인·전사에 부 구분, AI 지시문에 부별 정리 ③ 녹음 내려받기: 전체 / 모든 부 따로(파일 이름 _1부·_2부·_3부, 재생 가능한 길이)
④ .mnote 저장 → 다시 열기: 부 정보 유지, 부별 파일은 PC 서비스(/cut)로 m4a, PC 서비스가 없으면 이 기기에서 WAV
PC 서비스(localhost:8765)가 켜져 있으면 ④의 m4a 단계도 확인한다(꺼져 있으면 건너뜀).
"""
import asyncio, json, os, sys, tempfile, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    try: pc = bool(json.load(urllib.request.urlopen('http://localhost:8765/health', timeout=3)).get('cut'))
    except Exception: pc = False
    srv, url = smoke.serve(); out = tempfile.mkdtemp()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block', accept_downloads=True, permissions=['microphone'])
        await ctx.add_init_script(smoke.NO_LOGIN)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        await pg.evaluate("document.querySelector('#trOn') && (document.querySelector('#trOn').checked = false)")   # 실시간 전사는 끈다(가짜 마이크)
        # ① 녹음·나누기
        await pg.click('#recBtn'); await pg.wait_for_timeout(3500)
        expect(await pg.locator('#partBtn').is_visible() and await pg.text_content('#partBtn') == '2부 시작', '녹음 중 "2부 시작" 버튼')
        await pg.click('#partBtn'); await pg.wait_for_timeout(3000)
        await pg.click('#recBtn'); await pg.wait_for_timeout(1500)   # 일시정지(쉬는 시간)
        expect(await pg.evaluate("document.querySelector('#recBtn').dataset.state") == 'paused' and await pg.text_content('#partBtn') == '3부 시작', '일시정지 중 "3부 시작"')
        await pg.click('#partBtn'); await pg.wait_for_timeout(500)
        expect(await pg.evaluate("document.querySelector('#recBtn').dataset.state") == 'recording', '3부 시작 → 이어서 녹음')
        await pg.wait_for_timeout(3000)
        await pg.click('#stopBtn')
        for _ in range(40):
            await pg.wait_for_timeout(250)
            if await pg.evaluate("!!__meetnote.S.audioBlob"): break
        await pg.wait_for_timeout(800)
        parts = await pg.evaluate("__meetnote.S.parts")
        d = await pg.evaluate("__meetnote.S.duration")
        expect(len(parts) == 3 and parts[0]['t0'] == 0 and 2.5 < parts[1]['t0'] < 5 and parts[1]['t1'] == parts[2]['t0'] and abs(parts[2]['t1'] - d) < 0.6, f'부 3개·시각 {parts} dur={d}')
        expect(5 < parts[2]['t0'] < 8.5, f'쉬는 시간(일시정지)은 녹음 시간에 들어가지 않음 3부 시작={parts[2]["t0"]}')
        sizes = await pg.evaluate("__meetnote.partAudio.blobs.map(b => b && b.size)")
        expect(len(sizes) == 3 and all(s and s > 1000 for s in sizes), f'부별 녹음 파일 3개 {sizes}')
        # ② 표시·지시문
        await pg.evaluate("__meetnote.S.segments = [{t0:1,t1:2,text:'일부 이야기'},{t0:4.5,t1:5,text:'이부 이야기'},{t0:8,t1:9,text:'삼부 이야기'}]; __meetnote.renderTranscript ? __meetnote.renderTranscript() : 0")
        await pg.click('#tabTr'); await pg.wait_for_timeout(300)
        divs = await pg.eval_on_selector_all('.part-div span', 'xs => xs.map(x => x.textContent)')
        expect(divs == ['1부', '2부', '3부'], f'전사 목록에 부 구분선 {divs}')
        marks = await pg.locator('#reelMarks .pt').count()
        expect(marks == 2, f'타임라인에 2부·3부 표시 {marks}')
        pr = await pg.evaluate("__meetnote.buildPrompt('final')")
        expect('3부로 나눠 진행' in pr and '"1부", "2부"' in pr, '회의록 지시문에 부별 정리')
        # ③ 내려받기
        expect(await pg.locator('#audioDlBtn').is_visible(), '"녹음 내려받기" 버튼')
        await pg.click('#audioDlBtn'); await pg.wait_for_timeout(300)
        async with pg.expect_download() as dl: await pg.click('[data-choice="all"]')
        f = await dl.value; expect(f.suggested_filename.endswith('_녹음.webm'), f'전체 파일 {f.suggested_filename}')
        names = []
        async def grab(choice, n):
            await pg.click('#audioDlBtn'); await pg.wait_for_timeout(300)
            got = []
            def on_dl(d): got.append(d)
            pg.on('download', on_dl)
            await pg.click(f'[data-choice="{choice}"]')
            for _ in range(80):
                await pg.wait_for_timeout(250)
                if len(got) >= n: break
            pg.remove_listener('download', on_dl)
            res = []
            for d in got: path = os.path.join(out, d.suggested_filename); await d.save_as(path); res.append(path)
            return res
        files = await grab('each', 3)
        expect([os.path.basename(x).split('_녹음_')[-1] for x in files] == ['1부.webm', '2부.webm', '3부.webm'], f'모든 부 따로 {[os.path.basename(x) for x in files]}')
        durs = []
        for path in files:
            b64 = __import__('base64').b64encode(open(path, 'rb').read()).decode()
            durs.append(await pg.evaluate("async b => { const ab = Uint8Array.from(atob(b), c => c.charCodeAt(0)).buffer; const ctx = new AudioContext(); const buf = await ctx.decodeAudioData(ab); ctx.close(); return +buf.duration.toFixed(1); }", b64))
        expect(all(d > 1.5 for d in durs) and abs(sum(durs) - d) < 2.5, f'부별 파일 재생 길이 {durs} (합 ≈ {d})')
        # ④ 다시 연 회의: .mnote 저장 → 새 회의 → 열기 → 부 정보 유지, 부별 파일은 잘라 받기
        await pg.click('#saveBtn'); await pg.wait_for_timeout(150); await pg.click('#saveDlgGo'); await pg.fill('#textDlgInput', '부나누기')
        async with pg.expect_download() as dl: await pg.click('#textDlgYes')
        mn = os.path.join(out, 'parts.mnote'); await (await dl.value).save_as(mn)
        await pg.click('#newBtn'); await pg.wait_for_timeout(300)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes'); await pg.wait_for_timeout(300)
        await pg.set_input_files('#fileInput', mn); await pg.wait_for_timeout(1500)
        reopened = await pg.evaluate("__meetnote.S.parts")
        expect(reopened == parts and await pg.evaluate("!!__meetnote.S.audioBlob"), f'.mnote 다시 열기: 부 정보·녹음 유지 {reopened}')
        await pg.evaluate("__meetnote.partAudio = { id: '', blobs: [] }")   # 다른 날·다른 브라우저에서 연 것과 같은 상태(같은 화면에서 다시 열면 녹음 직후의 부별 파일을 그대로 쓴다)
        if pc:
            f2 = await grab('p2', 1)
            expect(f2 and f2[0].endswith('_2부.m4a') and os.path.getsize(f2[0]) > 1000, f'다시 연 회의: PC 서비스로 2부 잘라 받기 {[os.path.basename(x) for x in f2]}')
        else: print('SKIP PC 서비스 꺼짐 → /cut 단계 건너뜀')
        await ctx.route('http://localhost:8765/**', lambda r: r.abort()); await ctx.route('http://127.0.0.1:8765/**', lambda r: r.abort())
        f3 = await grab('p3', 1)
        expect(f3 and f3[0].endswith('_3부.wav') and os.path.getsize(f3[0]) > 1000, f'PC 서비스 없음: 이 기기에서 3부 WAV {[os.path.basename(x) for x in f3]}')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
