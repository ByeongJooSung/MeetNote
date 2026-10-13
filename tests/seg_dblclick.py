#!/usr/bin/env python3
"""전사 문단 더블클릭 수정 점검 (Playwright). 실행: python tests/seg_dblclick.py
① 더블클릭 → 바로 수정(커서는 누른 자리) → 입력 → Enter 저장 ② 녹음이 있을 때: 한 번 클릭은 그 자리부터 재생, 더블클릭은 재생하지 않고 수정
③ 우클릭 메뉴(수정·듣기·나누기·삭제)는 그대로
"""
import asyncio, io, math, os, struct, sys, tempfile, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

def tone_wav(sec=12):
    path = os.path.join(tempfile.gettempdir(), 'meetnote_tone.wav')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(16000 * sec)))
    return path

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
        await ctx.add_init_script(smoke.NO_LOGIN)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        await pg.set_input_files('#audioInput', tone_wav()); await pg.wait_for_timeout(1200)
        if await pg.locator('#analyzeDlg').is_visible(): await pg.click('#anaSkip')
        await pg.evaluate("__meetnote.S.segments = [{t0:1,t1:5,text:'안녕하세요 회의를 시작하겠습니다',spk:'0'},{t0:6,t1:10,text:'다음 안건은 예산입니다',spk:'1'}]; __meetnote.renderTranscript()")
        await pg.click('#tabTr'); await pg.wait_for_timeout(300)
        st = pg.locator('.seg[data-i="1"] .stext')
        # ② 한 번 클릭 → 잠깐 뒤 재생
        await st.click(position={'x': 5, 'y': 8}); await pg.wait_for_timeout(600)
        playing = await pg.evaluate("!__meetnote.audio.paused")
        t = await pg.evaluate("__meetnote.audio.currentTime")
        expect(playing and 5 <= t <= 7.5, f'한 번 클릭: 그 자리부터 재생 (재생={playing}, {t:.1f}초)')
        await pg.evaluate("__meetnote.audio.pause(); __meetnote.audio.currentTime = 0")
        # ①② 더블클릭 → 재생 없이 수정, 커서는 누른 자리
        box = await pg.evaluate("(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.seg[data-i=\"1\"] .stext')); const b = r.getClientRects()[0]; return { x: b.left, y: b.top, width: b.width, height: b.height }; })()")   # 글자가 차지한 영역(칸 전체가 아니라)
        await pg.mouse.dblclick(box['x'] + box['width'] * 0.45, box['y'] + box['height'] / 2); await pg.wait_for_timeout(500)
        editing = await pg.evaluate("(() => { const el = document.querySelector('.seg[data-i=\"1\"] .stext'); return el.isContentEditable && document.activeElement === el; })()")
        playing = await pg.evaluate("!__meetnote.audio.paused")
        caret = await pg.evaluate("getSelection().isCollapsed ? getSelection().anchorOffset : -1")
        expect(editing and not playing, f'더블클릭: 재생 없이 바로 수정 (수정={editing}, 재생={playing})')
        expect(3 <= caret <= 10, f'커서가 더블클릭한 자리에 {caret}')
        await pg.keyboard.press('End'); await pg.keyboard.type(' (수정)'); await pg.keyboard.press('Enter'); await pg.wait_for_timeout(300)
        expect(await pg.evaluate("__meetnote.S.segments[1].text") == '다음 안건은 예산입니다 (수정)', '입력 후 Enter로 저장')
        # ③ 우클릭 메뉴 그대로
        await pg.locator('.seg[data-i="0"] .stext').click(button='right'); await pg.wait_for_timeout(300)
        expect(await pg.locator('#segMenu').is_visible() and await pg.locator('#segMenu [data-segact="edit"]').count() == 1, '우클릭 메뉴(수정·듣기·나누기·삭제) 유지')
        await pg.click('#segMenu [data-segact="edit"]'); await pg.wait_for_timeout(300)
        expect(await pg.evaluate("document.querySelector('.seg[data-i=\"0\"] .stext').isContentEditable"), '우클릭 → 수정도 동작')
        await pg.keyboard.press('Escape')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
