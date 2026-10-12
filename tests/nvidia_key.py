#!/usr/bin/env python3
"""NVIDIA API 엔진 키 처리 점검 (Playwright, PC 서비스 /nim은 가짜로 대신). 실행: python tests/nvidia_key.py
① 예전(주소별)으로 저장된 키도 읽는다 ② "Authorization: Bearer nvapi-…"를 통째로 붙여 넣어도 nvapi-…만 보낸다
③ 서버 주소가 바뀌어도 키가 유지된다 ④ nvapi-가 아닌 값은 보내기 전에 막고 안내 ⑤ 키가 없으면 보내기 전에 안내
"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    srv, url = smoke.serve()
    sent = []
    async def fake_nim(route):
        r = route.request
        if r.url.endswith('/health'): return await route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'nim': True}))
        if '/v1/models' in r.url: return await route.fulfill(status=200, content_type='application/json', body=json.dumps({'data': [{'id': 'z-ai/glm-5.3-flash'}, {'id': 'nvidia/embed-qa-4'}]}))
        if '/v1/chat/completions' in r.url:
            sent.append(r.headers.get('authorization'))
            return await route.fulfill(status=200, content_type='application/json', body=json.dumps({'choices': [{'message': {'content': '## 회의 개요\n- 테스트'}}]}))
        return await route.fulfill(status=404, body='')
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
        await ctx.add_init_script(smoke.NO_LOGIN)
        await ctx.add_init_script("if (!sessionStorage.getItem('seeded')) { localStorage.setItem('meetnote.aiToken', JSON.stringify({'nvidia|https://integrate.api.nvidia.com': 'nvapi-OLD'})); sessionStorage.setItem('seeded', '1'); }")
        await ctx.route('http://localhost:8765/**', fake_nim)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        await pg.click('#settingsBtn'); await pg.click('[data-set="ai"]'); await pg.wait_for_timeout(300)
        await pg.select_option('#aiProvider', 'nvidia'); await pg.wait_for_timeout(300)
        expect(await pg.input_value('#aiToken') == 'nvapi-OLD', '예전(주소별) 저장 키를 읽음')
        await pg.fill('#aiToken', '  Authorization: Bearer "nvapi-NEW"  '); await pg.dispatch_event('#aiToken', 'input')
        expect(await pg.input_value('#aiToken') == 'nvapi-NEW', f"붙여 넣은 줄에서 키만 남김 {await pg.input_value('#aiToken')!r}")
        await pg.fill('#aiBase', 'http://localhost:8765/nim'); await pg.dispatch_event('#aiBase', 'change')
        await pg.click('#aiModels'); await pg.wait_for_timeout(2000)
        conn = await pg.text_content('#aiConnText')
        expect('모델 1개' in conn, f'임베딩 모델은 빼고 목록 {conn}')
        await pg.click('#aiDlgClose')
        await pg.evaluate("__meetnote.S.segments = [{t0:0,t1:3,text:'안녕하세요 회의를 시작합니다',spk:'A'}]")
        await pg.click('#tabAi'); await pg.wait_for_timeout(300)
        await pg.click('#aiGo'); await pg.wait_for_timeout(2500)
        expect(sent == ['Bearer nvapi-NEW'], f'주소가 바뀌어도 키 유지·정리된 키 전송 {sent}')
        # nvapi-가 아닌 값: 보내기 전에 막음
        sent.clear()
        await pg.evaluate("sessionStorage.setItem('meetnote.aiToken', JSON.stringify({ nvidia: 'abc123' })); localStorage.removeItem('meetnote.aiToken')")
        await pg.click('#aiGo'); await pg.wait_for_timeout(1500)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes'); await pg.wait_for_timeout(1500)
        body = await pg.evaluate('document.body.innerText')
        expect(not sent and 'nvapi-"로 시작해야' in body, f'nvapi-가 아닌 키는 보내지 않고 안내 sent={sent}')
        # 키 없음
        await pg.evaluate("sessionStorage.removeItem('meetnote.aiToken')")
        await pg.click('#aiGo'); await pg.wait_for_timeout(1500)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes'); await pg.wait_for_timeout(1500)
        expect(not sent and 'NVIDIA API 키가 없어요' in await pg.evaluate('document.body.innerText'), '키가 없으면 보내지 않고 안내')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
