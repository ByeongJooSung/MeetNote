#!/usr/bin/env python3
"""회의록 머리·주제·참석자 표·공동활용 플랫폼 양식·본문 그림 점검 (Playwright). 실행: python tests/minutes_coop.py
① 머리 제목 '회의록' 고정 ② 주제 → 파일 이름(공동활용 플랫폼 규칙), 파일 이름 → 주제
③ 참석자 표: 엑셀식 붙여넣기·칸 범위 선택·복사·지우기·사이에 넣기·줄 끌어 옮기기
④ 본문·메모 Ctrl+V 그림 ⑤ 공동활용 플랫폼 양식 HWPX·DOCX·PDF(HTML) 내보내기
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

COOP_NAME = 'CH_P_PM_10705_화학물질정보 공동활용 플랫폼 구축(1단계)_회의록 (3부.경과보고 회의)_20260508'
PASTE = """([sel, kind, text]) => {   // 실제 Ctrl+V와 같은 paste 이벤트(글 또는 그림 파일)
  const el = document.querySelector(sel); el.focus();
  const dt = new DataTransfer();
  if (kind === 'text') dt.setData('text/plain', text);
  else { const c = document.createElement('canvas'); c.width = 120; c.height = 80; const g = c.getContext('2d'); g.fillStyle = '#c33'; g.fillRect(0, 0, 120, 80);
    const bin = atob(c.toDataURL('image/png').split(',')[1]); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    dt.items.add(new File([u], 'cap.png', { type: 'image/png' })); }
  el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
}"""

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
        await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(400)

        # ① 머리 제목
        await pg.fill('#title', '화학물질정보처리시스템 구축 1단계 – 경과보고 회의')
        expect(await pg.text_content('#docTitle') == '회의록', '① 머리 제목은 회의 제목과 상관없이 "회의록"')

        # ② 주제 ↔ 파일 이름
        await pg.select_option('#tplSel', 'coop'); await pg.wait_for_timeout(100)
        expect(await pg.locator('#mEnd').is_visible(), '② 공동활용 플랫폼 양식: 종료 시각 칸 보임')
        expect(await pg.locator('#tplActions th[data-f="out"]').is_visible(), '② 실행계획에 산출물 열 보임')
        await pg.fill('#mWhen', '2026-05-08T16:30'); await pg.dispatch_event('#mWhen', 'change')
        await pg.fill('#mEnd', '17:30'); await pg.dispatch_event('#mEnd', 'change')
        await pg.fill('#mTopic', '3부.경과보고 회의')
        expect(await pg.evaluate('__meetnote.defaultFileName()') == COOP_NAME, '② 주제 → 파일 이름 규칙')
        expect(await pg.evaluate('__meetnote.dlBase()') == COOP_NAME, '② 내려받기 이름에 시각 덧붙이지 않음(날짜로 끝남)')
        expect(COOP_NAME in (await pg.text_content('#topicFile')), '② 주제 아래에 파일 이름 미리보기')
        await pg.evaluate("__meetnote.syncTopicFromName('CH_P_PM_10705_화학물질정보 공동활용 플랫폼 구축(1단계)_회의록 (요구사항 미팅_안전원)_20260518')")
        expect(await pg.input_value('#mTopic') == '요구사항 미팅_안전원', '② 파일 이름 → 주제 칸')
        await pg.fill('#mTopic', '3부.경과보고 회의')

        # ③ 참석자 표
        await pg.click('#attAdd')
        await pg.evaluate(PASTE, ['#attBody input[data-i="0"][data-att="org"]', 'text', '한국환경공단\t손창수\t부장\n한국환경공단\t이창수\t과장\n오상자이엘\t김대석\t이사\n'])
        att = await pg.evaluate('__meetnote.S.attendees.map(a => [a.org, a.name, a.title])')
        expect(att == [['한국환경공단', '손창수', '부장'], ['한국환경공단', '이창수', '과장'], ['오상자이엘', '김대석', '이사']], f'③ 엑셀 표 붙여넣기로 3줄 채움 {att}')
        a = await pg.locator('#attBody tr[data-r="0"] td[data-c="0"]').bounding_box()
        z = await pg.locator('#attBody tr[data-r="1"] td[data-c="1"]').bounding_box()
        await pg.mouse.move(a['x'] + 20, a['y'] + 10); await pg.mouse.down()
        await pg.mouse.move(z['x'] + 20, z['y'] + 10, steps=6); await pg.mouse.up()
        expect(await pg.locator('#attBody td.sel').count() == 4, '③ 끌어서 2×2 칸 선택')
        copied = await pg.evaluate("""() => { const dt = new DataTransfer(); document.activeElement.dispatchEvent(new ClipboardEvent('copy', { clipboardData: dt, bubbles: true, cancelable: true })); return dt.getData('text/plain'); }""")
        expect(copied == '한국환경공단\t손창수\n한국환경공단\t이창수', f'③ Ctrl+C: 탭·줄바꿈 글로 복사 {copied!r}')
        await pg.keyboard.press('Delete')
        expect(await pg.evaluate('__meetnote.S.attendees.slice(0, 2).map(a => a.org + a.name + "|" + a.title)') == ['|부장', '|과장'], '③ Delete: 고른 칸 지움')
        await pg.evaluate(PASTE, ['#attBody input[data-i="0"][data-att="org"]', 'text', '한국환경공단\t손창수\n한국환경공단\t이창수'])
        await pg.click('#attBody button[data-ins="0"]')
        att = await pg.evaluate('__meetnote.S.attendees.map(a => a.name)')
        expect(len(att) == 4 and att[1] == '' and await pg.evaluate('__meetnote.S.attendees[1].org') == '한국환경공단', '③ ＋: 그 줄 아래에 넣고 소속은 윗줄을 따름')
        await pg.click('#attBody button[data-del="1"]')
        h = pg.locator('#attBody tr[data-r="2"] td.h'); t0 = await pg.locator('#attBody tr[data-r="0"]').bounding_box()
        await h.drag_to(pg.locator('#attBody tr[data-r="0"]'), target_position={'x': 30, 'y': 3})
        att = await pg.evaluate('__meetnote.S.attendees.map(a => a.name)')
        expect(att == ['김대석', '손창수', '이창수'], f'③ ⋮⋮ 끌어 맨 위로 옮기기 {att}')

        # ④ 그림 붙여넣기
        await pg.click('#docEditor')
        await pg.evaluate(PASTE, ['#docEditor', 'img', ''])
        await pg.wait_for_timeout(600)
        src = await pg.evaluate("document.querySelector('#docEditor img')?.getAttribute('src') || ''")
        expect(src.startswith('data:image/jpeg;base64,'), '④ 회의 내용에 Ctrl+V 그림(JPEG로 줄여 넣음)')
        await pg.evaluate(PASTE, ['#editor', 'img', ''])
        await pg.wait_for_timeout(600)
        expect(await pg.evaluate("document.querySelectorAll('#editor img').length") == 1, '④ 메모에 Ctrl+V 그림')
        await pg.keyboard.type('그림 아래 글')
        await pg.wait_for_timeout(200)

        # ⑤ 내보내기
        await pg.evaluate("__meetnote.S.meta.actions = [{ due: '6월 중', who: '오상자이엘', what: '개발 서버 구축', out: '설계서' }]; __meetnote.S.meta.notes = 'WBS 일정 업데이트 필요'")
        opts = "{ attCompact: false, chips: false, notes: true, minutes: false, transcript: false, photos: false }"
        hx = await pg.evaluate(f"""async () => {{ const z = await JSZip.loadAsync(await __meetnote.buildHwpx({opts})); const sec = await z.file('Contents/section0.xml').async('string'); return {{ sec, bins: Object.keys(z.files).filter(k => k.startsWith('BinData/') && !k.endsWith('/')) }}; }}""")
        sec = hx['sec']
        for s, m in [('2026년 5월 8일 (금) 16:30 ~ 17:30', '일시(요일·종료)'), ('[한국환경공단] 손창수 부장, 이창수 과장', '소속별 참석자'), ('산출물', '산출물 열'), ('설계서', '실행계획 값'), ('ㅇ 특이사항', '특이사항'), ('회 의   세 부   내 용', '세부 내용 제목')]:
            expect(s in sec, f'⑤ HWPX: {m}')
        expect(len(hx['bins']) == 2 and sec.count('<hp:pic ') == 2, f'⑤ HWPX: 본문·메모 그림 2장 {hx["bins"]}')
        dx = await pg.evaluate(f"""async () => {{ const z = await JSZip.loadAsync(await __meetnote.buildDocx({opts})); return Object.keys(z.files).filter(k => k.startsWith('word/media/') && !k.endsWith('/')).length; }}""")
        expect(dx == 2, f'⑤ DOCX: 그림 2장 {dx}')
        html = await pg.evaluate(f"__meetnote.buildExportInto(__meetnote.htmlBuilder('t'), {opts}).build()")
        expect(html.count('<img') == 2 and '산출물' in html, '⑤ PDF(HTML): 그림 2장·산출물')

        expect(not errs, f'JS 오류 없음 {errs[:1]}')
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
