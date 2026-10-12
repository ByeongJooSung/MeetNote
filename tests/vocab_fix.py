#!/usr/bin/env python3
"""용어 사전(전사 교정) 점검 (Playwright). 실행: python tests/vocab_fix.py
① 설정 → 용어 사전 저장 ② 녹음 중 실시간 전사(pushSegment)와 분석 결과(cleanSegments)에 바로 적용 — 영문은 낱말 단위(said 그대로), 한글은 조사째
③ 바른 표기가 인식 힌트(meetingVocab) 맨 앞 ④ 전사 문단을 고치면 바뀐 낱말만 골라 사전에 넣을지 묻고, 넣으면 뒤 전사도 자동 교정
⑤ "모두 바꾸기"도 사전에 넣을지 묻는다
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
        await ctx.add_init_script(smoke.NO_LOGIN)
        pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300)
        # ① 설정에서 저장
        await pg.click('#settingsBtn'); await pg.click('[data-set="vocab"]'); await pg.wait_for_timeout(200)
        await pg.fill('#vocabText', 'ANYID = aid, 에이아이디, 애니 아이디\nK-CHESAR = 케이 체사르\n화학물질안전원')
        await pg.click('#vocabSave'); await pg.wait_for_timeout(200)
        st = await pg.text_content('#vocabState')
        expect('3개 용어' in st and '교정 표기 4개' in st and await pg.evaluate("localStorage.getItem('meetnote.vocab')"), f'용어 사전 저장 {st}')
        await pg.click('#aiDlgClose')
        # ② 실시간·분석 결과
        await pg.evaluate("__meetnote.pushSegment({ t0: 0, t1: 3, text: 'aid 로그인은 에이아이디가 맡고 said는 그대로, AID도' })")
        t = await pg.evaluate("__meetnote.S.segments[0].text")
        expect(t == 'ANYID 로그인은 ANYID가 맡고 said는 그대로, ANYID도', f'실시간 전사 교정(영문 낱말 단위·한글 조사째) {t!r}')
        r = await pg.evaluate("__meetnote.cleanSegments([{ t0: 5, t1: 8, text: '애니아이디 연동은 케이체사르와' }]).map(g => g.text)")
        expect(r == ['ANYID 연동은 K-CHESAR와'], f'분석 결과 교정(띄어쓰기 차이 허용) {r}')
        # ③ 인식 힌트
        v = await pg.evaluate("__meetnote.meetingVocab()")
        expect(v[:3] == ['ANYID', 'K-CHESAR', '화학물질안전원'], f'바른 표기가 인식 힌트 맨 앞 {v[:4]}')
        # ④ 문단 수정 → 바뀐 낱말만 제안 → 넣으면 뒤 전사도 교정
        await pg.click('#tabTr'); await pg.wait_for_timeout(200)
        await pg.evaluate("__meetnote.pushSegment({ t0: 20, t1: 24, text: '오늘은 엔이디 기능을 봅니다.' }); __meetnote.suggestVocab('오늘은 엔이디가 맞아요', '오늘은 NID가 맞아요')")
        await pg.wait_for_timeout(200)
        sug = await pg.text_content('#vocabSugText')
        expect(await pg.locator('#vocabSug').is_visible() and '“엔이디” → “NID”' in sug and '1곳' in sug, f'고친 낱말만 골라 제안(조사 제외) {sug!r}')
        await pg.click('#vocabSugYes'); await pg.wait_for_timeout(200)
        vt = await pg.evaluate("__meetnote.vocabText")
        segs = await pg.evaluate("__meetnote.S.segments.map(g => g.text).join(' | ')")
        expect('NID = 엔이디' in vt and '엔이디' not in segs and 'NID 기능' in segs, f'사전에 넣고 지금 전사도 교정 {segs!r}')
        await pg.evaluate("__meetnote.pushSegment({ t0: 60, t1: 63, text: '다음 엔이디 일정' })")
        expect(await pg.evaluate("__meetnote.S.segments.at(-1).text") == '다음 NID 일정', '그 뒤에 들어온 전사도 자동 교정')
        await pg.evaluate("document.querySelector('#vocabSug').hidden = true")
        big = await pg.evaluate("(() => { __meetnote.suggestVocab('가 나 다 라 마', '하 하 하 하 하'); return document.querySelector('#vocabSug').hidden; })()")
        expect(big, '낱말 4개 이상 바꾼 고쳐 쓰기는 묻지 않음')
        # ⑤ 모두 바꾸기 → 제안
        await pg.evaluate("__meetnote.pushSegment({ t0: 90, t1: 93, text: '블록체인 기반 아이디 지갑' })")
        await pg.click('#trReplaceToggle'); await pg.fill('#trSearch', '아이디 지갑'); await pg.fill('#trReplace', 'ID Wallet'); await pg.click('#trReplaceAll'); await pg.wait_for_timeout(300)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes'); await pg.wait_for_timeout(300)
        expect(await pg.locator('#vocabSug').is_visible() and '“아이디 지갑” → “ID Wallet”' in await pg.text_content('#vocabSugText'), '모두 바꾸기도 사전에 넣을지 제안')
        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
