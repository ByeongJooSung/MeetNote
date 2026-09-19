#!/usr/bin/env python3
"""MeetNote 스모크 테스트 (Playwright). 실행: python tests/smoke.py [--check-only]
- 문법 점검(node --check), 편집기·표·메모 시점·AI 초안 넣기(표·칩)·작성 옵션/템플릿·설정(AI 작성·작성자·버전)·
  내보내기(HWPX/DOCX)·저장(파일 이름 입력)/불러오기·불러오기 창(목록·달력)을 확인한다.
- 앱은 web/ 을 127.0.0.1 임시 포트로 띄워서 연다(디버그 훅 __meetnote 는 localhost 에서만 열린다). 로그인 게이트는 빈 설정으로 우회한다.
"""
import asyncio, functools, http.server, os, re, subprocess, sys, tempfile, threading, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
HTML = os.path.join(WEB, 'index.html')
NO_LOGIN = "Object.defineProperty(window, 'MEETNOTE_CONFIG', { value: { googleClientId: '', requireLogin: false }, writable: false });"

def check_syntax():
    s = open(HTML, encoding='utf-8').read()
    js = re.findall(r'<script data-app>(.*?)</script>', s, re.S)[-1]
    tmp = os.path.join(tempfile.gettempdir(), 'meetnote_app.js'); open(tmp, 'w', encoding='utf-8').write(js)
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    print('syntax:', 'OK' if r.returncode == 0 else r.stderr); return r.returncode == 0

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=WEB))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://localhost:{srv.server_address[1]}/index.html'

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(cond, msg):
        nonlocal ok; print(('PASS ' if cond else 'FAIL ') + msg); ok = ok and bool(cond)
    srv, url = serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(accept_downloads=True, viewport={'width': 1400, 'height': 900}, service_workers='block'); pg = await ctx.new_page()
        await ctx.add_init_script(NO_LOGIN)
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        jz = os.environ.get('MEETNOTE_JSZIP')  # 오프라인 환경: 로컬 jszip.min.js 경로를 주면 CDN 대신 사용
        if jz: await pg.route('https://cdnjs.cloudflare.com/**', lambda r: r.fulfill(path=jz, content_type='application/javascript'))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.fill('#title', '스모크 회의'); await pg.fill('#mPlace', '테스트실')
        await pg.click('#attAdd'); await pg.fill('input[data-att="name"][data-i="0"]', '홍길동')
        # 본문: 제목 + 표 + 마크다운 목록
        await pg.locator('#docEditor').click(); await pg.click('[data-pop="block"]:visible'); await pg.click('[data-block="h2"]:visible'); await pg.keyboard.type('안건'); await pg.keyboard.press('Enter')
        await pg.click('[data-pop="table"]:visible'); await pg.click('[data-tr="2"][data-tc="2"]:visible'); await pg.keyboard.type('A1'); await pg.keyboard.press('Tab'); await pg.keyboard.type('B1')
        expect(await pg.locator('#docEditor table').count() == 1, '본문 표 생성')
        await pg.locator('#docEditor td').nth(0).click(); await pg.keyboard.press('ArrowDown')
        await pg.keyboard.press('ArrowDown'); await pg.keyboard.press('ArrowDown'); await pg.keyboard.type('- '); await pg.keyboard.type('항목')
        expect(await pg.locator('#docEditor ul li').count() >= 1, '마크다운 목록 단축')
        # 메모 + 시점
        await pg.click('#tabMemo'); await pg.locator('#editor').click(); await pg.keyboard.type('메모 한 줄')
        await pg.evaluate("__meetnote.trackBlocks(__meetnote.memoTrack,{structural:true})")
        expect(await pg.evaluate("__meetnote.S.blocks.length") == 1, '메모 블록 추적')
        # AI 초안 → 회의록: 마크다운 기호 없이 서식·표로 들어가는지
        md = '\n'.join(['## 결정 사항', '- **예산** 확정 [01:05]', '  - 세부 *항목*', '', '| 할 일 | 담당 | 근거 |', '|---|---|---|', '| 견적 요청 | 홍길동 | [02:10] |', '| 일정 공유 | (확인 필요) | [03:00] |', ''])
        await pg.evaluate("md => { const m = __meetnote; m.S.minutes = md; m.appendToDoc(m.mdToDocNodes(md, true)); }", md)
        doc_text = await pg.inner_text('#docEditor')
        expect(await pg.locator('#docEditor table').count() == 2 and '|' not in doc_text and '**' not in doc_text and '##' not in doc_text, 'AI 초안 표·서식 그대로 넣기')
        expect(await pg.locator('#docEditor td .tchip').count() == 2 and await pg.locator('#docEditor li li em').count() == 1, '표 안 시점 칩 · 중첩 목록 · 기울임')
        n_th = await pg.evaluate("md => { const d = document.createElement('div'); d.innerHTML = __meetnote.mdToHtml(md); return d.querySelectorAll('th').length; }", '\n'.join(['| 할 일 | 근거 |', '|---|---|', '| 가 |  |']))
        expect(n_th == 1, '시간 숨김 시 빈 근거 열 제거')
        # 작성 옵션(작성 화면): 시간 표시 · 추가 지시 · 템플릿
        await pg.click('#tabAi'); await pg.click('#draftOptBtn')
        await pg.fill('#meetExtra', '결정 사항을 맨 위에 요약'); await pg.click('#tplSave'); await pg.fill('#textDlgInput', '요약 우선'); await pg.click('#textDlgYes'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#draftTplSel option', has_text='요약 우선').count() == 1, '추가 지시 템플릿 저장')
        await pg.fill('#meetExtra', '결정 사항을 맨 위에 요약하고 담당자를 굵게'); await pg.click('#tplSave'); await pg.wait_for_timeout(200)
        tpls = await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.draftTpls'))")
        expect(len(tpls) == 1 and tpls[0]['text'].endswith('굵게'), '추가 지시 템플릿 수정(덮어쓰기)')
        await pg.uncheck('#aiTimes'); await pg.wait_for_timeout(100)
        expect(await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.draftOpt')).times") is False, '타임라인 시간 표시 옵션 저장')
        await pg.check('#aiTimes'); await pg.click('#draftOptCancel')
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('담당자를 굵게' in prompt and '마크다운 표로 정리' in prompt, '프롬프트에 추가 지시·표 규칙 반영')
        # 설정: AI 작성(전역 지시문) · 작성자 · 버전 정보
        await pg.click('#settingsBtn'); await pg.click('[data-set="draft"]')
        await pg.click('#setDraft [data-opt="tables"] [data-v="false"]'); await pg.fill('#draftExtra', '용어는 영어 그대로'); await pg.click('#draftOptOk'); await pg.wait_for_timeout(100)
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('용어는 영어 그대로' in prompt and '마크다운 표로 정리' not in prompt, '설정의 전역 지시문 수정')
        await pg.click('#setDraft [data-opt="tables"] [data-v="true"]'); await pg.click('#draftOptOk')
        await pg.click('[data-set="author"]'); await pg.fill('#setAuthorOrg', '개발팀'); await pg.fill('#setAuthorName', '김작성'); await pg.click('#setAuthorApply'); await pg.wait_for_timeout(100)
        expect(await pg.input_value('#mAuthor') == '개발팀 / 김작성', '설정의 작성자 반영')
        await pg.click('[data-set="about"]')
        expect((await pg.inner_text('#aboutVer')).startswith('v0.') and await pg.locator('#patchNotes li').count() > 0, '버전 정보 · 패치 노트')
        await pg.click('#aiDlgClose')
        expect(await pg.locator('#playBtn svg').count() == 2 and (await pg.inner_text('#playBtn')).strip() == '', '재생 버튼 아이콘')
        has_zip = await pg.evaluate("!!window.JSZip")
        if not has_zip: print('SKIP 내보내기/저장 (JSZip을 불러오지 못함: 인터넷 또는 MEETNOTE_JSZIP 필요)')
        # 내보내기 DOCX / HWPX (부록: AI 초안 → 표 유지)
        for fmt in (['docx', 'hwpx'] if has_zip else []):
            await pg.click('#hwpxBtn'); await pg.click(f'input[name="expFmt"][value="{fmt}"]'); await pg.check('#hxMinutes')
            async with pg.expect_download() as dl: await pg.click('#hwpxGo')
            d = await dl.value; path = os.path.join(tempfile.gettempdir(), 'smoke.' + fmt); await d.save_as(path)
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                expect(('word/document.xml' in names) if fmt == 'docx' else ('Contents/section0.xml' in names), f'{fmt} 내보내기')
                if fmt == 'docx': expect('| 담당' not in z.read('word/document.xml').decode('utf-8'), 'docx 부록의 AI 초안 표 변환')
        # 저장/불러오기
        if not has_zip: expect(not errs, f'JS 오류 없음 {errs[:2]}'); await b.close(); srv.shutdown(); return ok
        await pg.click('#saveBtn'); await pg.fill('#textDlgInput', '스모크_저장')
        async with pg.expect_download() as dl: await pg.click('#textDlgYes')
        d = await dl.value; mn = os.path.join(tempfile.gettempdir(), 'smoke.mnote'); await d.save_as(mn)
        expect(d.suggested_filename == '스모크_저장.mnote', '저장 시 파일 이름 입력')
        await pg.click('#newBtn'); await pg.wait_for_timeout(200)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes')
        expect(await pg.input_value('#mAuthor') == '개발팀 / 김작성', '새 회의에 작성자 기본값')
        await pg.set_input_files('#fileInput', mn); await pg.wait_for_timeout(800)
        expect(await pg.input_value('#mPlace') == '테스트실' and await pg.locator('#docEditor table').count() == 2, '.mnote 저장/불러오기 왕복')
        expect(await pg.evaluate("__meetnote.S.aiExtra") == '결정 사항을 맨 위에 요약하고 담당자를 굵게', '추가 지시 .mnote 왕복')
        expect(not errs, f'JS 오류 없음 {errs[:2]}')
        await b.close()
    srv.shutdown()
    return ok

if __name__ == '__main__':
    good = check_syntax()
    if '--check-only' not in sys.argv:
        good = asyncio.run(run()) and good
    print('RESULT:', 'OK' if good else 'FAIL'); sys.exit(0 if good else 1)
