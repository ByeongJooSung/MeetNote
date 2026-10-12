#!/usr/bin/env python3
"""계정별 프로젝트 분리 · 접속 기록 · 관리자 페이지 점검 (Playwright, 계정 DB는 가짜 Firestore로 대신). 실행: python tests/accounts_admin.py
① 같은 브라우저의 예전 공용 프로젝트 목록 → 새 계정은 자기가 마스터·초대된 것만 보인다(초대 안 된 남의 프로젝트는 안 보임)
② 서버가 더는 주지 않는(내보내진) 남의 프로젝트는 목록에서 빠진다
③ 로그인하면 accounts·logins에 기록되고, 관리자 이메일에만 "관리자 페이지"가 보이며 사용자·프로젝트·접속 이력이 나온다
"""
import asyncio, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke

ADMIN = 'tjdqudwn@gmail.com'
def cfg_script():
    return "Object.defineProperty(window, 'MEETNOTE_CONFIG', { value: { googleClientId: '', requireLogin: false, firebase: { apiKey: 'k', projectId: 'p' }, adminEmails: ['%s'] }, writable: false });" % ADMIN

def sv(v):
    if isinstance(v, bool): return {'booleanValue': v}
    if isinstance(v, int): return {'integerValue': str(v)}
    if isinstance(v, list): return {'arrayValue': {'values': [sv(x) for x in v]}}
    return {'stringValue': str(v)}
def unv(f):
    o = {}
    for k, v in (f or {}).items():
        o[k] = int(v['integerValue']) if 'integerValue' in v else v.get('booleanValue') if 'booleanValue' in v else [x.get('stringValue') for x in v.get('arrayValue', {}).get('values', [])] if 'arrayValue' in v else v.get('stringValue')
    return o

class FakeFS:
    def __init__(self): self.docs = {}; self.writes = []
    def doc(self, path, data): return {'name': 'projects/p/databases/(default)/documents/' + path, 'fields': {k: sv(v) for k, v in data.items()}}
    async def handle(self, route):
        req = route.request; url = req.url; m = re.search(r'/documents(/[^?:]*)?(:runQuery)?', url); path = (m.group(1) or '').strip('/'); body = req.post_data or ''
        def ok(o, st=200): return route.fulfill(status=st, content_type='application/json', body=json.dumps(o))
        if m.group(2):   # runQuery
            q = json.loads(body)['structuredQuery']; col = q['from'][0]['collectionId']
            rows = [(p, d) for p, d in self.docs.items() if p.count('/') == 1 and p.startswith(col + '/')]
            w = q.get('where', {}).get('fieldFilter')
            if w:
                f, v, op = w['field']['fieldPath'], w['value']['stringValue'], w['op']
                rows = [(p, d) for p, d in rows if (v in (d.get(f) or [])) if op == 'ARRAY_CONTAINS'] if op == 'ARRAY_CONTAINS' else [(p, d) for p, d in rows if d.get(f) == v]
            if q.get('orderBy'): rows.sort(key=lambda x: x[1].get('at', ''), reverse=True)
            return await ok([{'document': self.doc(p, d)} for p, d in rows] or [{}])
        if req.method == 'GET':
            if path in self.docs: return await ok(self.doc(path, self.docs[path]))
            kids = [(p, d) for p, d in self.docs.items() if p.startswith(path + '/') and p.count('/') == path.count('/') + 1]
            if kids or path.count('/') % 2 == 0 and path.split('/')[-1] in ('accounts', 'projects', 'meetings', 'logins'): return await ok({'documents': [self.doc(p, d) for p, d in kids]})
            return await ok({'error': {'code': 404, 'message': 'not found'}}, 404)
        if req.method == 'PATCH':
            data = unv(json.loads(body).get('fields')); self.docs[path] = {**self.docs.get(path, {}), **data}; self.writes.append(('PATCH', path)); return await ok(self.doc(path, self.docs[path]))
        if req.method == 'POST':
            pid = path + '/auto' + str(len(self.docs)); self.docs[pid] = unv(json.loads(body).get('fields')); self.writes.append(('POST', path)); return await ok(self.doc(pid, self.docs[pid]))
        if req.method == 'DELETE': self.docs.pop(path, None); return await ok({})
        return await ok({})

def proj_doc(pid, name, owner_email, members, owner_uid='u-' ):
    return {'json': json.dumps({'id': pid, 'name': name, 'refs': [], 'merged': '', 'updatedAt': '2026-10-01T00:00:00.000Z', 'ownerEmail': owner_email, 'members': members}), 'name': name, 'updatedAt': '2026-10-01T00:00:00.000Z', 'deleted': False, 'owner': 'uid-' + owner_email.split('@')[0], 'ownerEmail': owner_email, 'memberEmails': [owner_email] + members}

async def run():
    from playwright.async_api import async_playwright
    ok = True
    def expect(c, m):
        nonlocal ok; print(('PASS ' if c else 'FAIL ') + m); ok = ok and bool(c)
    srv, url = smoke.serve()
    legacy = [{'id': 'p1', 'name': '남의 프로젝트', 'ownerEmail': 'a@x.com', 'owner': 'uid-a', 'members': [], 'refs': [], 'updatedAt': '2026-10-01T00:00:00.000Z'},
              {'id': 'p2', 'name': '초대받은 프로젝트', 'ownerEmail': 'a@x.com', 'owner': 'uid-a', 'members': ['new@x.com'], 'refs': [], 'updatedAt': '2026-10-01T00:00:00.000Z'},
              {'id': 'p3', 'name': '게스트 프로젝트', 'refs': [], 'updatedAt': '2026-10-01T00:00:00.000Z'}]
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def page_as(email, fs, seed_legacy=None, bucket=None):
            ctx = await b.new_context(viewport={'width': 1400, 'height': 900}, service_workers='block')
            await ctx.add_init_script(cfg_script())
            sub = 's-' + email.split('@')[0]; exp = int(time.time()) + 3600
            seed = {'meetnote.user': json.dumps({'sub': sub, 'email': email, 'name': email.split('@')[0], 'exp': exp}),
                    'meetnote.fb': json.dumps({'sub': sub, 'uid': 'uid-' + email.split('@')[0], 'idToken': 't', 'refreshToken': 'r', 'exp': int(time.time() * 1000) + 3600000})}
            if seed_legacy is not None: seed['meetnote.projects'] = json.dumps(seed_legacy)
            if bucket is not None: seed['meetnote.projects.' + sub] = json.dumps(bucket)
            await ctx.add_init_script("if (!sessionStorage.getItem('seeded')) { const o = %s; for (const k in o) localStorage.setItem(k, o[k]); sessionStorage.setItem('seeded', '1'); }" % json.dumps(seed))
            await ctx.route('https://firestore.googleapis.com/**', fs.handle)
            await ctx.route('https://www.googleapis.com/**', lambda r: r.fulfill(status=401, body='{}'))
            pg = await ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            await pg.goto(url); await pg.wait_for_timeout(2500)
            return ctx, pg, errs
        names = "__meetnote.projects().map(p => p.name).sort()"
        # ① 새 계정: 예전 공용 목록에서 초대받은 것만
        fs = FakeFS(); fs.docs['projects/p2'] = proj_doc('p2', '초대받은 프로젝트', 'a@x.com', ['new@x.com']); fs.docs['projects/p1'] = proj_doc('p1', '남의 프로젝트', 'a@x.com', [])
        ctx, pg, errs = await page_as('new@x.com', fs, seed_legacy=legacy)
        n = await pg.evaluate(names)
        expect(n == ['초대받은 프로젝트'], f'새 계정에는 초대받은 프로젝트만 {n}')
        store = await pg.evaluate("Object.keys(localStorage).filter(k => k.startsWith('meetnote.projects'))")
        expect('meetnote.projects.s-new' in store, f'프로젝트를 계정별로 보관 {store}')
        expect(await pg.locator('#adminOpen').is_hidden(), '일반 계정에는 관리자 페이지 없음')
        expect(('PATCH', 'accounts/uid-new') in fs.writes and ('POST', 'logins') in fs.writes, f'로그인 기록(accounts·logins) {fs.writes[:4]}')
        expect(not errs, f'JS 오류 없음 {errs[:1]}'); await ctx.close()
        # ② 내보내진 프로젝트: 브라우저에 있어도 서버가 안 주면 빠진다
        fs2 = FakeFS(); fs2.docs['projects/p1'] = proj_doc('p1', '남의 프로젝트', 'a@x.com', [])
        ctx, pg, errs = await page_as('new@x.com', fs2, bucket=[legacy[1]])
        n = await pg.evaluate(names)
        expect(n == [], f'초대가 취소된 프로젝트는 목록에서 빠짐 {n}')
        await ctx.close()
        # ③ 관리자
        fs3 = FakeFS()
        fs3.docs['accounts/uid-new'] = {'email': 'new@x.com', 'name': 'new', 'firstAt': '2026-10-01T01:00:00.000Z', 'lastAt': '2026-10-02T01:00:00.000Z', 'logins': 3, 'ua': 'Windows · Chrome 154'}
        fs3.docs['logins/l1'] = {'uid': 'uid-new', 'email': 'new@x.com', 'name': 'new', 'at': '2026-10-02T01:00:00.000Z', 'ua': 'Windows · Chrome 154'}
        fs3.docs['projects/p2'] = proj_doc('p2', '초대받은 프로젝트', 'a@x.com', ['new@x.com'])
        fs3.docs['users/uid-new/meetings/m1'] = {'title': '회의', 'fileId': 'f', 'updatedAt': '2026-10-02'}
        ctx, pg, errs = await page_as(ADMIN, fs3)
        if await pg.locator('#dashPage').is_hidden(): await pg.evaluate("document.querySelector('#backDash') && document.querySelector('#backDash').click()")
        await pg.wait_for_timeout(500)
        expect(await pg.locator('#adminOpen').is_visible(), '관리자 계정에는 대시보드에 "관리자 페이지"')
        await pg.click('#adminOpen'); await pg.wait_for_timeout(1500)
        t = await pg.inner_text('#admBody')
        expect('new@x.com' in t and '초대받은 프로젝트' in t and ADMIN in t, f'사용자 탭: 가입 사용자·프로젝트 {t[:200]!r}')
        await pg.click('[data-adm="projects"]'); t = await pg.inner_text('#admBody')
        expect('초대받은 프로젝트' in t and 'a@x.com' in t and 'new@x.com' in t, '프로젝트 탭: 마스터·구성원')
        await pg.click('[data-adm="logins"]'); t = await pg.inner_text('#admBody')
        expect(t.count('new@x.com') >= 1 and ADMIN in t, f'접속 이력 탭 {t[:160]!r}')
        expect(not errs, f'JS 오류 없음 {errs[:1]}'); await ctx.close()
        await b.close()
    srv.shutdown()
    print('RESULT:', 'OK' if ok else 'FAIL')

if __name__ == '__main__': asyncio.run(run())
