#!/usr/bin/env python3
"""MeetNote 스모크 테스트 (Playwright). 실행: python tests/smoke.py [--check-only]
- 문법 점검(node --check), 편집기·표·메모 시점·AI 초안 넣기(표·칩)·작성 옵션/템플릿·설정(AI 작성·작성자·버전)·
  내보내기(HWPX/DOCX)·저장(파일 이름 입력)/불러오기·불러오기 창(목록·달력)을 확인한다.
- 앱은 web/ 을 127.0.0.1 임시 포트로 띄워서 연다(디버그 훅 __meetnote 는 localhost 에서만 열린다). 로그인 게이트는 빈 설정으로 우회한다.
"""
import asyncio, functools, http.server, json, os, re, subprocess, sys, tempfile, threading, zipfile
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
        # 저장된 프로젝트가 있는 브라우저로 시작(시작 시점 초기화 오류 회귀 점검)
        await ctx.add_init_script("try { localStorage.setItem('meetnote.projects', JSON.stringify([{ id: 'p-old', name: '이전 프로젝트', refs: [{ id: 'r1', name: '문서', kind: 'md', chars: 10, summary: '요약', addedAt: '' }], merged: '## 요약', updatedAt: '2026-09-22T00:00:00.000Z' }])); } catch {}")
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        jz = os.environ.get('MEETNOTE_JSZIP')  # 오프라인 환경: 로컬 jszip.min.js 경로를 주면 CDN 대신 사용
        if jz: await pg.route('https://cdnjs.cloudflare.com/**', lambda r: r.fulfill(path=jz, content_type='application/javascript'))
        await pg.goto(url); await pg.wait_for_timeout(1800)
        if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
        await pg.wait_for_timeout(700)
        expect(await pg.locator('#dashPage').is_visible() and await pg.locator('#dashProjs button').count() >= 2, '시작 시 대시보드 표시')
        # 목록의 모든 행에 프로젝트 선택·삭제가 보여야 한다(첫 행만 보이던 회귀)
        await pg.evaluate("__meetnote.cloudRows = [1, 2, 3].map(i => ({ id: 'm' + i, title: '회의 ' + i, fileId: 'F' + i, when: '2026-09-2' + i + 'T10:00', updatedAt: '2026-09-2' + i + 'T11:00:00Z' })); __meetnote.renderCloudList('db')")
        await pg.click('[data-cview="list"]'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#cloudList .cl-item').count() == 3 and await pg.locator('#cloudList .cl-projsel').count() == 3 and await pg.locator('#cloudList [data-cdel]').count() == 3, '목록 모든 행에 프로젝트 선택·삭제 표시')
        await pg.evaluate("__meetnote.cloudRows = []; __meetnote.renderCloudList('db')")
        expect(await pg.locator('#cloudClose').is_hidden(), '처음 대시보드에는 "편집 화면으로"가 없음(이 세션에서 편집한 적 없음)')
        await pg.click('#dashNew'); await pg.wait_for_timeout(200)
        await pg.click('#backDash'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#cloudClose').is_visible(), '편집 화면에 들어간 뒤에는 "편집 화면으로" 표시')
        await pg.click('#cloudClose'); await pg.wait_for_timeout(200)
        expect(await pg.evaluate("!!window.__meetnote && __meetnote.projects().length === 1") and not errs, f'저장된 프로젝트가 있어도 정상 시작 {errs[:1]}')
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
        # AI 초안 나눠 넣기: 할 일 → 실행계획, 추가로 확인할 점 → 특이사항
        md2 = chr(10).join(['## 할 일', '| 할 일 | 담당 | 기한 | 근거 |', '|---|---|---|---|', '| 견적 요청 | 홍길동 | 9/25 | [04:00] |', '- [ ] 요구사항 검토 (담당: 김과장, 기한: 10월 초)', '## 추가로 확인할 점', '- 예산 승인 절차 확인 [06:00]'])
        r = await pg.evaluate("md => __meetnote.insertDraft(md)", md2)
        acts = await pg.evaluate("__meetnote.S.meta.actions.map(a => [a.due, a.who, a.what])")
        expect(r['todo'] == 2 and r['note'] == 1 and ['9/25', '홍길동', '견적 요청'] in acts and ['10월 초', '김과장', '요구사항 검토'] in acts and '예산 승인 절차 확인' == (await pg.input_value('#mNotes')).strip() and '요구사항 검토' not in await pg.inner_text('#docEditor'), f'초안 나눠 넣기(실행계획·특이사항) {r} {acts}')
        expect(await pg.locator('#tplActions thead th').count() == 4, '실행계획 산출물 열 제거')
        # 작성 옵션(작성 화면): 시간 표시 · 추가 지시 · 템플릿
        await pg.click('#tabAi'); await pg.click('#draftOptBtn')
        await pg.fill('#meetExtra', '결정 사항을 맨 위에 요약'); await pg.click('#tplSave'); await pg.fill('#textDlgInput', '요약 우선'); await pg.click('#textDlgYes'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#draftTplSel option', has_text='요약 우선').count() == 1, '추가 지시 템플릿 저장')
        await pg.fill('#meetExtra', '결정 사항을 맨 위에 요약하고 담당자를 굵게'); await pg.click('#tplSave'); await pg.wait_for_timeout(200)
        tpls = await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.draftTpls'))")
        expect(len(tpls) == 1 and tpls[0]['text'].endswith('굵게'), '추가 지시 템플릿 수정(덮어쓰기)')
        await pg.uncheck('#aiTimes'); await pg.wait_for_timeout(100)
        expect(await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.draftOpt')).times") is False, '타임라인 시간 표시 옵션 저장')
        await pg.click('#srcSeg [data-src="transcript"]'); pr_t = await pg.evaluate("__meetnote.buildPrompt() || ''"); await pg.click('#srcSeg [data-src="both"]')
        expect('메모 한 줄' not in pr_t and (await pg.evaluate("JSON.parse(localStorage.getItem('meetnote.draftOpt')).source")) == 'both', '초안 자료 선택(전사만 → 메모 제외)')
        await pg.check('#aiTimes'); await pg.click('#draftOptCancel')
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('담당자를 굵게' in prompt and '마크다운 표로 정리' in prompt, '프롬프트에 추가 지시·표 규칙 반영')
        # 설정: AI 작성(전역 지시문) · 작성자 · 버전 정보
        await pg.click('#settingsBtn'); await pg.click('[data-set="draft"]')
        await pg.click('#setDraft [data-opt="tables"] [data-v="false"]'); await pg.fill('#draftExtra', '용어는 영어 그대로'); await pg.click('#draftOptOk'); await pg.wait_for_timeout(100)
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('용어는 영어 그대로' in prompt and '마크다운 표로 정리' not in prompt, '설정의 전역 지시문 수정')
        await pg.click('#setDraft [data-opt="tables"] [data-v="true"]'); await pg.click('#draftOptOk')
        await pg.click('[data-set="author"]'); await pg.fill('#setAuthorOrg', '개발팀'); await pg.fill('#setAuthorName', '김작성'); await pg.fill('#setAuthorTitle', '책임'); await pg.click('#setAuthorApply'); await pg.wait_for_timeout(100)
        expect(await pg.input_value('#mAuthor') == '개발팀 / 김작성 책임', '설정의 작성자 반영')
        expect(await pg.evaluate("__meetnote.S.attendees.some(a => a.name === '김작성' && a.org === '개발팀' && a.title === '책임')"), '작성자를 참석자에 포함')
        # 참석자: AI 응답 파싱·병합, 같은 소속은 직급 최고 1명 + 외 N인
        ans = '```json' + chr(10) + json.dumps([{'org': '개발팀', 'name': '박이사', 'title': '이사'}, {'org': '개발팀', 'name': '최사원', 'title': '사원'}, {'org': '', 'name': '홍길동', 'title': '부장'}], ensure_ascii=False) + chr(10) + '```'
        r = await pg.evaluate("ans => { const m = __meetnote; const list = m.parseAttendeeJson(ans); const res = m.mergeAttendees(list); m.HW.attCompact = true; return { n: list.length, res, lines: m.attendeesByOrg(), rank: [m.titleRank('부사장') < m.titleRank('상무'), m.titleRank('수석연구원') < m.titleRank('연구원'), m.titleRank('대표이사') < m.titleRank('이사')] }; }", ans)
        expect(r['n'] == 3 and r['res']['added'] == 2 and '[개발팀] 박이사 이사 외 2인' in r['lines'] and all(r['rank']), f"참석자 캡처 응답 파싱 · 외 N인 표기 {r['lines']}")
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
            expect(re.fullmatch(r'스모크 회의_[0-9]{8}_[0-9]{6}[.]' + fmt, d.suggested_filename), f'{fmt} 파일 이름: 회의록 이름_날짜시분초')
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                expect(('word/document.xml' in names) if fmt == 'docx' else ('Contents/section0.xml' in names), f'{fmt} 내보내기')
                if fmt == 'docx':
                    x = z.read('word/document.xml').decode('utf-8')
                    expect('| 담당' not in x, 'docx 부록의 AI 초안 표 변환')
                    expect('Noto Sans KR' in x and 'Malgun' not in x, 'docx 글꼴 Noto Sans KR')
                    expect('김작성 책임' in x and '[개발팀] 박이사 이사 외 2인' in x and '최사원' not in x, 'docx 작성자 줄바꿈 · 같은 소속 외 N인')
                else: expect('Noto Sans KR' in z.read('Contents/header.xml').decode('utf-8'), 'hwpx 글꼴 Noto Sans KR')
        # 저장/불러오기
        if not has_zip: expect(not errs, f'JS 오류 없음 {errs[:2]}'); await b.close(); srv.shutdown(); return ok
        await pg.click('#saveBtn'); await pg.wait_for_timeout(150)
        expect(await pg.locator('#saveDlg').is_visible() and await pg.is_disabled('input[name="saveHow"][value="cloud"]') and await pg.is_checked('input[name="saveHow"][value="local"]'), '저장 방식 선택 창(로그인 전엔 .mnote만)')
        await pg.click('#saveDlgGo'); await pg.fill('#textDlgInput', '스모크_저장')
        async with pg.expect_download() as dl: await pg.click('#textDlgYes')
        d = await dl.value; mn = os.path.join(tempfile.gettempdir(), 'smoke.mnote'); await d.save_as(mn)
        expect(re.fullmatch(r'스모크_저장_[0-9]{8}_[0-9]{6}[.]mnote', d.suggested_filename), f'저장 시 파일 이름 입력 + 날짜시분초 ({d.suggested_filename})')
        # 이탈 확인: 새 회의 시작에서는 묻지 않고, 대시보드로 나갈 때만(한 번) 묻는다
        await pg.fill('#title', '스모크 수정됨'); await pg.wait_for_timeout(100)
        await pg.click('#backDash'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#confirmDlg').is_visible(), '대시보드 이탈 시 저장 확인')
        await pg.click('#confirmNo'); await pg.wait_for_timeout(100)
        await pg.click('#newBtn'); await pg.wait_for_timeout(200)
        expect(not await pg.locator('#confirmDlg').is_visible(), '새 회의 시작은 확인 없이 진행')
        expect(await pg.input_value('#mAuthor') == '개발팀 / 김작성 책임' and await pg.evaluate("__meetnote.S.attendees.length === 1"), '새 회의에 작성자 기본값(참석자 포함)')
        await pg.set_input_files('#fileInput', mn); await pg.wait_for_timeout(800)
        expect(await pg.input_value('#mPlace') == '테스트실' and await pg.locator('#docEditor table').count() == 2, '.mnote 저장/불러오기 왕복')
        expect(await pg.evaluate("__meetnote.S.aiExtra") == '결정 사항을 맨 위에 요약하고 담당자를 굵게', '추가 지시 .mnote 왕복')
        # 전사 파일 가져오기(클로바노트 .txt): 요약/음성 기록 × 시간 있음/없음
        head = ['주간 회의', '2026.07.03 금 오후 2:16 ・ 109분 32초', '홍길동', '', '']
        summ = ['AI 맞춤 요약', '주요 주제', '', '• 예산', '• 일정', '', '다음 할 일', '', '• 견적 요청', '', '', '시간대별 요약']
        blocks_t = ['01:31~02:25', '예산 논의', '• 예산을 10% 늘림', '• 집행은 10월', '105:18~109:09', '일정 논의', '• 출시는 10월 말']
        blocks_n = [l for l in blocks_t if '~' not in l]
        foot = ['', '', 'clovanote.naver.com', '', 'AI가 요약한 결과가 포함되어 있습니다.']
        voice_t = ['참석자 1 00:03', '안녕하세요. 시작하겠습니다.', '', '참석자 2 01:10', '네 예산부터 보시죠.', '', '참석자 1 61:05', '좋습니다.']
        voice_n = ['참석자 1', '안녕하세요. 시작하겠습니다.', '', '참석자 2', '네 예산부터 보시죠.', '', '참석자 1', '좋습니다.']
        parse = lambda lines: pg.evaluate("t => { const p = __meetnote.parseTranscriptText(t); return { kind: p.kind, timed: p.timed, n: p.segs.length, first: p.segs[0], last: p.segs[p.segs.length - 1], topics: p.topics.length, todos: p.todos.length, dur: p.duration, title: p.title, spk: p.segs.filter(g => g.spk).length }; }", '﻿' + '\r\n'.join(lines))
        r = await parse(head + summ + blocks_t + foot)
        expect(r['kind'] == 'summary' and r['timed'] and r['n'] == 5 and r['first']['t0'] == 91 and r['last']['t0'] >= 105 * 60 + 18 and r['topics'] == 2 and r['todos'] == 1 and r['dur'] == 6572 and r['title'] == '주간 회의', '클로바 AI 요약(시간 있음) 파싱')
        r = await parse(head + summ + blocks_n + foot)
        expect(r['kind'] == 'summary' and not r['timed'] and r['n'] == 5 and r['first']['text'] == '■ 예산 논의' and r['last']['t1'] <= 6572.01, '클로바 AI 요약(시간 없음) 파싱')
        r = await parse(head + voice_t)
        expect(r['kind'] == 'transcript' and r['timed'] and r['n'] == 3 and r['spk'] == 3 and r['last']['t0'] == 3665 and r['first']['spk'] == '참석자 1', '클로바 음성 기록(시간 있음) 파싱')
        r = await parse(head + voice_n)
        expect(r['kind'] == 'transcript' and not r['timed'] and r['n'] == 3 and r['spk'] == 3 and r['first']['text'].startswith('안녕하세요'), '클로바 음성 기록(시간 없음) 파싱')
        await pg.click('#newBtn'); await pg.wait_for_timeout(200)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes')
        txt = os.path.join(tempfile.gettempdir(), 'smoke_clova.txt'); open(txt, 'w', encoding='utf-8-sig', newline='').write('\r\n'.join(head + summ + blocks_n + foot))
        await pg.set_input_files('#trInput', txt); await pg.wait_for_timeout(500)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes')   # 주요 주제·다음 할 일을 메모에 넣기
        await pg.wait_for_timeout(300)
        expect(await pg.locator('#segList .seg').count() == 5 and await pg.locator('#segList .ts').count() == 0 and await pg.input_value('#title') == '주간 회의', '전사 파일 가져오기(시간 없음: 시각 숨김, 제목 채움)')
        expect(await pg.locator('#editor li').count() == 3, '요약의 주요 주제·다음 할 일을 메모에 넣기')
        expect(await pg.is_disabled('#recBtn') and await pg.is_disabled('#attachBtn'), '전사를 가져오면 녹음·녹음 파일 붙이기 잠금')
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('시간 정보가 없습니다' in prompt and '[00:' not in prompt.split('<전사')[1], '시간 없는 전사: 프롬프트에서 시각 제외')
        await pg.click('#tabTr'); await pg.click('#trImportClear'); await pg.click('#confirmYes'); await pg.wait_for_timeout(200)
        expect(await pg.locator('#segList .seg').count() == 0 and not await pg.is_disabled('#recBtn'), '가져온 전사 지우기 → 녹음 가능')
        # 전사: 발언자 색 시각 · 검색 · 우클릭 수정 · 실시간 전사 문단 끊기
        await pg.evaluate("(() => { const m = __meetnote; m.S.segments = [{ t0: 2, t1: 5, text: '첫 문단 예산 이야기', spk: '0' }, { t0: 10, t1: 30, text: '둘째 문단 챗봇 학습 이야기', spk: '1' }]; m.renderTranscript(); })()")
        await pg.click('#tabTr'); await pg.evaluate("document.querySelector('#toast').hidden = true")
        expect(await pg.evaluate("[...document.querySelectorAll('#segList .seg')].every(r => r.querySelector('.ts').dataset.k === r.querySelector('.spk').dataset.k && getComputedStyle(r.querySelector('.ts')).color === getComputedStyle(r.querySelector('.spk')).color)"), '전사 시각 색 = 발언자 색')
        await pg.fill('#trSearch', '챗봇'); await pg.wait_for_timeout(150)
        expect(await pg.locator('#segList .seg').count() == 1 and await pg.locator('#segList mark').count() == 1 and '1 / 2' in await pg.inner_text('#trSearchInfo'), '전사 검색: 낱말이 든 문단만')
        await pg.fill('#trSearch', ''); await pg.click('#segList .seg[data-i="0"] .stext', button='right'); await pg.click('#segMenu [data-segact="edit"]')
        await pg.keyboard.press('End'); await pg.keyboard.type(' 수정됨'); await pg.keyboard.press('Enter'); await pg.wait_for_timeout(150)
        expect(await pg.evaluate("__meetnote.S.segments[0].text") == '첫 문단 예산 이야기 수정됨', '전사 우클릭 → 문단 수정')
        n_par = await pg.evaluate("(() => { const m = __meetnote; m.S.segments = []; const put = (t0, t1, text) => m.pushSegment({ t0, t1, text }); put(0, 3, '회의를 시작하겠습니다.'); put(3.4, 6, '안건은 세 가지입니다.'); put(7.2, 10, '첫 번째는 예산입니다.'); put(21, 24, '다음 안건으로 가겠습니다.'); const n = m.S.segments.length; m.S.segments = []; m.renderTranscript(); return n; })()")
        expect(n_par == 3, f'실시간 전사 문단을 짧게 끊음 ({n_par}문단)')
        # 클라우드 STT(모의 응답): 화자 표시를 0,1,…로 맞추고 용어 사전을 보냄
        await pg.route('https://api.deepgram.com/**', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps({'metadata': {'duration': 30}, 'results': {'utterances': [{'speaker': 3, 'start': 0.5, 'end': 3, 'transcript': '안녕하세요'}, {'speaker': 1, 'start': 3.2, 'end': 8, 'transcript': '예산 이야기'}]}})))
        r = await pg.evaluate("(() => { const m = __meetnote; m.S.audioBlob = new Blob([new Uint8Array(1000)], { type: 'audio/webm' }); m.S.segments = []; m.setCloudKey('deepgram', 'dg-test'); Object.assign(m.diarState(), { mode: 'cloud', cloud: { prov: 'deepgram', url: '', keep: false, vocab: true } }); return m.diarizeCloud({ title: 't' }).then(() => ({ segs: m.S.segments.map(g => [g.spk, g.text]), vocab: m.meetingVocab().slice(0, 3), keyLocal: !!localStorage.getItem('meetnote.cloudKeys') })); })()")
        expect(r['segs'] == [['0', '안녕하세요'], ['1', '예산 이야기']] and '홍길동' in r['vocab'] and not r['keyLocal'], f'클라우드 STT(Deepgram 모의) 결과·화자 번호·용어 사전 {r}')
        if await pg.locator('#mapDlg').is_visible(): await pg.click('#mapCancel')
        await pg.evaluate("(() => { const m = __meetnote; m.S.audioBlob = null; m.S.segments = []; Object.assign(m.diarState(), { mode: 'browser' }); m.renderTranscript(); })()")
        # 브라우저 내장 분석 옵션: 모델 등급·발언자 수 UI와 등급 결정
        await pg.evaluate("(() => { const m = __meetnote; m.S.audioBlob = new Blob([new Uint8Array(1000)], { type: 'audio/webm' }); Object.assign(m.diarState(), { mode: 'browser', tier: 'auto', n: 0 }); })()")
        await pg.click('#tabTr'); await pg.click('#diarBtn'); await pg.wait_for_timeout(200)
        expect(await pg.is_visible('#diarTier') and await pg.input_value('#diarTier') == 'auto', '브라우저 내장: 인식 모델 선택 UI')
        await pg.select_option('#diarTier', 'accurate'); await pg.fill('#diarBN', '3'); await pg.press('#diarBN', 'Tab'); await pg.wait_for_timeout(100)
        r = await pg.evaluate("(() => { const d = JSON.parse(localStorage.getItem('meetnote.diar')); return { tier: d.tier, n: d.n, note: document.querySelector('#diarBrowserNote').textContent }; })()")
        expect(r['tier'] == 'accurate' and r['n'] == 3 and '목소리 특징' in r['note'], f'브라우저 내장 옵션 저장·안내 {r["tier"]} {r["n"]}')
        await pg.click('#diarCancel'); await pg.evaluate("(() => { const m = __meetnote; m.S.audioBlob = null; Object.assign(m.diarState(), { tier: 'auto', n: 0 }); })()")
        # 프로젝트: 만들기 → 회의에 지정 → 참고 문서(요약 없이 md) 통합 → 프롬프트 반영
        await pg.select_option('#projSel', '__new'); await pg.fill('#textDlgInput', '스모크 프로젝트'); await pg.click('#textDlgYes'); await pg.wait_for_timeout(200)
        pid = await pg.evaluate("__meetnote.S.meta.project")
        expect(bool(pid) and await pg.evaluate("__meetnote.projects().length") == 2, '프로젝트 생성·회의에 지정')
        pmd = os.path.join(tempfile.gettempdir(), '프로젝트 규칙.md'); open(pmd, 'w', encoding='utf-8').write('## 용어' + chr(10) + '- K-CHESAR: 위해성 평가 모델')
        await pg.click('#projManage'); await pg.set_input_files('#projRefInput', pmd); await pg.wait_for_timeout(800); await pg.click('#projClose')
        pr = await pg.evaluate("__meetnote.projects().find(p => p.name === '스모크 프로젝트')")
        expect(len(pr['refs']) == 1 and 'K-CHESAR' in pr['merged'], '프로젝트 참고 문서(md) → 통합 참조 문서')
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        expect('<프로젝트 참고 "스모크 프로젝트"' in prompt and 'K-CHESAR' in prompt and '<참고 자료>가 <프로젝트 참고>보다 우선' not in prompt, '프롬프트에 프로젝트 참고 반영')
        # 참고 자료: 파일 → 글 변환(원본은 보관하지 않음), 프롬프트에는 참고용으로만, 출처 표시
        docx = os.path.join(tempfile.gettempdir(), '스모크 제안서.docx')
        with zipfile.ZipFile(docx, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="x"><w:body><w:p><w:r><w:t>플랫폼 구축 제안</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>항목</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>예산 &amp; 기간</w:t></w:r></w:p></w:tc></w:tr></w:tbl>' + ''.join(f'<w:p><w:r><w:t>부록 {i}. 연혁과 통계를 나열한 긴 문단입니다. 조직 현황과 일반 사항을 길게 설명합니다.</w:t></w:r></w:p>' for i in range(400)) + '<w:p><w:r><w:t>위해성 평가 모델은 K-CHESAR 2.0을 사용한다.</w:t></w:r></w:p></w:body></w:document>')
        hwp = os.path.join(tempfile.gettempdir(), 'smoke_old.hwp'); open(hwp, 'wb').write(b'\xd0\xcf\x11\xe0')
        await pg.set_input_files('#refInput', [docx, hwp]); await pg.wait_for_timeout(1200)
        refs = await pg.evaluate("__meetnote.S.refs.map(r => ({ name: r.name, kind: r.kind, text: r.text.slice(0, 40), keys: Object.keys(r).sort().join() }))")
        expect(len(refs) == 1 and refs[0]['name'] == '스모크 제안서' and '항목 | 예산 & 기간' in refs[0]['text'] and 'blob' not in refs[0]['keys'] and '.hwp' in await pg.inner_text('#toast'), '참고 자료 변환(docx → 글, hwp는 안내)')
        await pg.evaluate("__meetnote.S.segments.push({ t0: 5, t1: 9, text: '위해성 평가 모델은 케이 체사르를 씁니다. 주차장 안내도 논의했습니다.' })")
        prompt = await pg.evaluate("__meetnote.buildPrompt()")
        blk = prompt[prompt.rindex('<참고 자료'):]
        expect('K-CHESAR' in blk and blk.count('부록 ') < 30 and '[자료 1: 스모크 제안서]' in blk, '참고 자료: 회의와 겹치는 대목만 골라 보냄')
        expect('회의에서 언급되지 않은 내용은 회의록에 넣지 마세요' in prompt and '하나도 빠뜨리지 말고' in prompt and '(자료: 자료 이름)' in prompt, '참고 자료 규칙(참고만 · 회의 내용 누락 금지 · 출처 표시)')
        expect('<참고 자료>가 <프로젝트 참고>보다 우선' in prompt, '회의 참고 자료가 프로젝트 문서보다 우선')
        await pg.evaluate("(() => { const m = __meetnote; m.appendToDoc(m.mdToDocNodes('- K-CHESAR 2.0 사용 (자료: 스모크 제안서) [00:05]', true)); })()")
        expect(await pg.evaluate("(() => { const s = document.querySelector('#docEditor li span[style*=\"--tc-blue\"]'); return !!s && s.textContent === '(자료: 스모크 제안서)'; })()"), '출처 표시가 회의록에서 구분됨')
        await pg.click('#saveBtn'); await pg.click('#saveDlgGo'); await pg.fill('#textDlgInput', '스모크_자료')
        async with pg.expect_download() as dl: await pg.click('#textDlgYes')
        d = await dl.value; mn2 = os.path.join(tempfile.gettempdir(), 'smoke_refs.mnote'); await d.save_as(mn2)
        with zipfile.ZipFile(mn2) as z: names = z.namelist()
        expect('refs.json' in names and not any(n.endswith('.docx') for n in names), '.mnote에는 변환된 글만 저장(원본 파일 없음)')
        await pg.click('#newBtn'); await pg.wait_for_timeout(200)
        if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes')
        await pg.set_input_files('#fileInput', mn2); await pg.wait_for_timeout(800)
        expect(await pg.locator('#refList .ref-item').count() == 1, '참고 자료 .mnote 왕복')
        expect(await pg.evaluate("__meetnote.S.meta.project") == pid, '프로젝트 지정 .mnote 왕복')
        expect(not errs, f'JS 오류 없음 {errs[:2]}')
        await b.close()
    srv.shutdown()
    return ok

if __name__ == '__main__':
    good = check_syntax()
    if '--check-only' not in sys.argv:
        good = asyncio.run(run()) and good
    print('RESULT:', 'OK' if good else 'FAIL'); sys.exit(0 if good else 1)
