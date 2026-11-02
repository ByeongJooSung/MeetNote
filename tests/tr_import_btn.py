#!/usr/bin/env python3
"""전사 파일 가져오기 버튼 점검 (Playwright). 실행: python tests/tr_import_btn.py
① 녹음이 없는 새 회의: 버튼이 보이고 누를 수 있다 ② 녹음 파일을 붙인 회의: 버튼은 그대로 보이되 비활성 + 이유 툴팁
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke
from seg_dblclick import tone_wav

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
        await ctx.add_init_script(smoke.NO_LOGIN)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        await pg.click('#tabTr'); await pg.wait_for_timeout(200)
        btn = pg.locator('#trImportBtn')
        expect(await btn.is_visible() and await btn.is_enabled(), '① 녹음 없는 회의: 버튼 보임·누를 수 있음')
        expect('클로바노트' in (await btn.get_attribute('title') or ''), '① 툴팁: 가져올 수 있는 파일 안내')
        await pg.set_input_files('#audioInput', tone_wav(3)); await pg.wait_for_timeout(1200)
        if await pg.locator('#analyzeDlg').is_visible(): await pg.click('#anaSkip')
        await pg.click('#tabTr'); await pg.wait_for_timeout(200)
        expect(await pg.evaluate("!!__meetnote.S.audioBlob"), '녹음 파일이 붙음')
        expect(await btn.is_visible() and await btn.is_disabled(), '② 녹음 있는 회의: 버튼은 보이되 비활성')
        expect('녹음이 있어서' in (await btn.get_attribute('title') or ''), '② 툴팁: 가져올 수 없는 이유와 방법')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
