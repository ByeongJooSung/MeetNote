#!/usr/bin/env python3
"""Google Meet(Gemini 회의록) 가져오기 점검 (Playwright). 실행: python tests/gemini_import.py [스크립트.md 요약.md]
- 합성 예시(아래 TRANSCRIPT·SUMMARY)로 ① 스크립트+요약 .md 두 파일 한 번에 ② 스크립트만 → 요약만(전사는 두고 메모만)
  ③ Docs API 응답(탭 두 개) → docBodyText → parseGemini ④ 한 문서에 회의 두 개면 시간대 고르기 를 확인한다.
- 실제 Gemini 회의록 .md 두 개를 인자로 주면 그 파일로도 ①을 돌린다(개인 회의 내용이라 저장소에 넣지 말 것).
"""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

TRANSCRIPT = r'''9월 30, 2026

## **회의 일정: 2026년 9월 30일 10:33 KST \- 스크립트**

### **00:00:04**

**김하나：**안녕하세요. 오늘은 직무 분석 일정을 정하겠습니다.

**박두리：**네. 좋습니다. 시안은 금요일까지 보내겠습니다.

**김하나：**KPI는 계산식만 적어 주세요.

### **00:01:10**

**박두리：**알겠습니다. 프로젝트 관리와 운영 지원은 묶는 게 좋겠습니다.

**김하나：**네. 그렇게 정리하죠.

### **00:02:00 후 스크립트 작성이 종료되었습니다.**

*수정 가능한 이 스크립트는 컴퓨터에서 생성되었으며, 오류가 포함되어 있을 수 있습니다.*
'''
SUMMARY = r'''9월 30, 2026

## **회의 일정: 2026년 9월 30일 10:33 KST**

회의 기록 [스크립트](https://docs.google.com/document/d/abc/edit?tab=t.xyz)

### **요약**

직무 분석 일정 합의

**직무 묶기**
프로젝트 관리와 운영 지원을 하나로 묶기로 함.

### **다음 단계**

- [ ] \[박두리\] 시안 작성: 금요일까지 시안을 보내십시오.

### **상세정보**

* **일정**: 김하나는 일정을 설명하였다 ([00:00:04](?tab=t.xyz#heading=h.a)).
* **직무 묶기**: 두 사람은 묶기로 합의하였다 ([00:01:10](?tab=t.xyz#heading=h.b)).

*Gemini가 작성한 회의록이 정확한지 검토해야 합니다.*
'''

def docs_json():   # Docs API documents.get(includeTabsContent=true) 모양(필요한 부분만)
    def para(text, style='NORMAL_TEXT', bullet=False, runs=None):
        p = {'elements': runs or [{'textRun': {'content': text + '\n'}}], 'paragraphStyle': {'namedStyleType': style}}
        if bullet: p['bullet'] = {'listId': 'x'}
        return {'paragraph': p}
    memo = [para('회의 일정: 2026년 9월 30일 10:33 KST', 'HEADING_2'), para('요약', 'HEADING_3'), para('직무 분석 일정 합의'),
            para('다음 단계', 'HEADING_3'), para('[박두리] 시안 작성', bullet=True), para('상세정보', 'HEADING_3'), para('일정: 설명 (00:00:04).', bullet=True)]
    script = [para('회의 일정: 2026년 9월 30일 10:33 KST - 스크립트', 'HEADING_2'), para('00:00:04', 'HEADING_3'),
              para('', runs=[{'person': {'personProperties': {'name': '김하나'}}}, {'textRun': {'content': '：안녕하세요.\n'}}]),
              para('박두리：네.'), para('00:00:30', 'HEADING_3'), para('김하나：정리하죠.')]
    tab = lambda i, t, c: {'tabProperties': {'tabId': i, 'title': t}, 'documentTab': {'body': {'content': c}}}
    return {'title': '직무 인터뷰 - 2026/09/30 10:33 KST - Gemini가 작성한 메모', 'tabs': [tab('t.memo', '메모', memo), tab('t.script', '스크립트', script)]}

async def run(real):
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    d = tempfile.mkdtemp(); tp, sp = os.path.join(d, 'script.md'), os.path.join(d, 'summary.md')
    open(tp, 'w', encoding='utf-8').write(TRANSCRIPT); open(sp, 'w', encoding='utf-8').write(SUMMARY)
    srv, url = smoke.serve()
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
        await ctx.add_init_script(smoke.NO_LOGIN)
        async def fresh():
            pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            await pg.goto(url); await pg.wait_for_timeout(1800)
            if await pg.locator('#gateSkip').is_visible(): await pg.click('#gateSkip')
            await pg.wait_for_timeout(700); await pg.click('#dashNew'); await pg.wait_for_timeout(300); await pg.click('#tabTr')
            return pg, errs
        async def confirm_all(pg, n=3):
            for _ in range(n):
                await pg.wait_for_timeout(400)
                if await pg.locator('#confirmDlg').is_visible(): await pg.click('#confirmYes')
        st = "(() => { const S = __meetnote.S; return { n: S.segments.length, spk: [...new Set(S.segments.map(g => g.spk))], when: S.meta.when, im: S.trImport, att: S.attendees.map(a => a.name), memo: document.querySelector('#editor').innerText, t: S.segments.map(g => [g.t0, g.t1]), dur: S.duration, attach: !document.querySelector('#attachBtn').disabled }; })()"
        # ① 두 파일 한 번에
        pg, errs = await fresh()
        await pg.set_input_files('#trInput', [tp, sp]); await confirm_all(pg)
        s = await pg.evaluate(st)
        expect(s['n'] == 5 and set(s['spk']) == {'김하나', '박두리'}, f"두 파일: 스크립트 5줄·발언자 2명 {s['n']} {s['spk']}")
        expect(s['when'] == '2026-09-30T01:33:00.000Z', f"회의 시각 = 2026-09-30 10:33 KST {s['when']}")
        expect(s['t'][0][0] == 4 and s['t'][3][0] == 70 and all(a <= b for a, b in s['t']) and s['dur'] == 120, f"시각: 구간 시작·끝(00:02:00) 반영 {s['t']} dur={s['dur']}")
        expect('다음 단계' in s['memo'] and '[박두리] 시안 작성' in s['memo'] and '요약 (Gemini)' in s['memo'] and '(00:01:10)' in s['memo'] and 'Gemini가 작성한' not in s['memo'], f'요약·다음 단계·상세정보가 메모로(링크·안내 문구 제거) {s["memo"]!r}')
        expect('수정 가능한' not in await pg.evaluate("__meetnote.S.segments.map(g => g.text).join(' ')"), '스크립트 꼬리말(안내 문구)이 발언에 붙지 않음')
        expect(s['im']['src'] == 'gemini' and s['im']['kind'] == 'transcript' and s['attach'], 'Gemini 스크립트: 녹화 붙이기 허용')
        expect({'김하나', '박두리'} <= set(s['att']), '발언자를 참석자로')
        expect(not errs, f'JS 오류 없음 {errs[:1]}'); await pg.close()
        # ② 스크립트 → 요약(전사 유지, 메모만)
        pg, errs = await fresh()
        await pg.set_input_files('#trInput', tp); await confirm_all(pg, 2)
        n1 = (await pg.evaluate(st))['n']
        await pg.set_input_files('#trInput', sp); await confirm_all(pg, 2)
        s = await pg.evaluate(st)
        expect(n1 == 5 and s['n'] == 5 and s['im']['kind'] == 'transcript' and '다음 단계' in s['memo'], f'요약만 따로 가져오면 전사는 두고 메모만 {n1}→{s["n"]}')
        await pg.close()
        # ③ Docs API 응답 → 탭별 글 → 회의
        pg, errs = await fresh()
        r = await pg.evaluate("(d) => { const texts = d.tabs.map(t => __meetnote.docBodyText(t.documentTab.body)); const ss = texts.flatMap((t, i) => __meetnote.parseGemini(t, d.tabs[i].tabProperties.tabId) || []); const m = ss.find(s => s.utts.length); return { texts, n: ss.length, keys: ss.map(s => s.key), utts: m && m.utts.map(u => [u.spk, u.t]), todos: ss.flatMap(s => s.todos) }; }", docs_json())
        expect(r['keys'] == ['2026-09-30 10:33', '2026-09-30 10:33'] and r['utts'] == [['김하나', 4], ['박두리', 4], ['김하나', 30]] and r['todos'] == ['[박두리] 시안 작성'], f"Docs API 탭 → 같은 회의로 묶임·사람 칩 이름 {r['keys']} {r['utts']} {r['todos']}")
        # 링크 창: 로그인 없이 문서 링크를 넣으면 로그인 안내(오류 없이)
        await pg.click('#meetBtn'); await pg.fill('#meetDoc', 'https://docs.google.com/document/d/1irxpEuN5hoWod4hSegJDiRBpC99HMlT2YOnqGlGCZb8/edit?tab=t.sikr63o4wbng'); await pg.click('#meetYes'); await pg.wait_for_timeout(800)
        expect(not await pg.locator('#meetDlg').is_visible() and '로그인' in await pg.evaluate("document.body.innerText") and not errs, f'링크 가져오기: 로그인 전이면 로그인 안내 {errs[:1]}')
        # ④ 한 문서에 회의 두 개 → 시간대 고르기
        two = SUMMARY + '\n\n' + SUMMARY.replace('10:33', '14:00').replace('직무 분석 일정 합의', '오후 회의')
        n = await pg.evaluate("(t) => (__meetnote.parseGemini(t) || []).map(s => s.label)", two)
        expect(n == ['2026년 9월 30일 10:33 KST', '2026년 9월 30일 14:00 KST'], f'회의 두 개를 시간대로 구분 {n}')
        expect(await pg.evaluate("__meetnote.parseGemini('참석자 1 00:05\\n안녕하세요') === null"), '클로바노트 등 다른 형식은 Gemini로 보지 않음')
        await pg.close()
        if real:
            pg, errs = await fresh()
            await pg.set_input_files('#trInput', real); await confirm_all(pg)
            s = await pg.evaluate(st)
            expect(s['n'] > 50 and len(s['spk']) >= 2 and s['when'] and '다음 단계' in s['memo'] and not errs, f"실제 회의록: {s['n']}줄 · 발언자 {s['spk']} · {s['when']} · 길이 {s['dur']}s")
            await pg.close()
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run(sys.argv[1:3] if len(sys.argv) > 2 else None))
