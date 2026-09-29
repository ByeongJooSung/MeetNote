#!/usr/bin/env node
/* 브라우저 내장 발언자 구분(워커)의 알고리즘 점검 — 모델 없이 돌아간다. 실행: node tests/diar_algo.js
   - web/index.html 의 DIAR_WORKER_SRC 를 꺼내 Node vm 에서 실행하고, 분할 모델·목소리 특징 모델을 가짜로 바꿔 끼운다.
   - 가짜 분할 모델: 오디오 표본값에 적힌 정답 화자 번호를 읽어, 창마다 처음 나온 순서로 지역 번호(최대 3명)를 매긴다(실제 모델처럼 창마다 번호가 제멋대로).
   - 가짜 목소리 특징: 화자마다 정해진 방향 + 잡음(같은 사람 거리 ≈0.5, 다른 사람 ≈1.4).
   - 창 단위 분할(segmentWindows) → 화자 통일(unifyWindows) → 단어 배정(assignWords) 결과가 정답과 맞는지 본다.
   실제 모델 품질은 tests/eval_stt.py(실제 녹음 + 정답 전사)로 잰다 */
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
const a = html.indexOf('const DIAR_WORKER_SRC = `'), b = html.indexOf('}`;', a);
if (a < 0 || b < 0) throw new Error('DIAR_WORKER_SRC를 찾지 못함');
const tpl = html.slice(a + 'const DIAR_WORKER_SRC = '.length, b + 2);
const src = new Function('TJS_URL', 'SEG_ID', 'EMB_ID', 'WHISPER_TIERS', 'return ' + tpl)('x', 'seg', 'emb', {});
const logs = [];
const ctx = { self: { postMessage: m => { if (m.type === 'log') logs.push(m.msg); } }, console, Float32Array, Math, Map, Set, Array, String, Number, Object, JSON, Infinity };
vm.createContext(ctx);
vm.runInContext(src + '\n;globalThis.__t = { segmentWindows, unifyWindows, assignWords, clusterVecs, findTurns, unifyAny, set: (m, p, e) => { segModel = m; segProc = p; embed = e; } };', ctx);
const T = ctx.__t;

// ---- 가짜 데이터 ----
let seed = 7; const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const gauss = () => { let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
const SR = 1000, FR = 0.02;   // 표본은 1kHz(모델이 없으니 충분), 분할 프레임 20ms
function makeTruth(nSpk, seconds, overlapProb = 0.08) {
  const turns = []; let t = 0.5, prev = -1;
  while (t < seconds - 2) {
    let s; do { s = Math.floor(rnd() * nSpk); } while (s === prev); prev = s;
    const d = 0.8 + rnd() * 9, gap = rnd() < 0.3 ? 0.2 + rnd() * 1.5 : 0.05;
    turns.push({ t0: t, t1: Math.min(seconds, t + d), spk: s });
    if (rnd() < overlapProb && turns.length > 1) turns.push({ t0: t + d * 0.5, t1: t + d * 0.5 + 0.6, spk: (s + 1) % nSpk, backchannel: true });
    t += d + gap;
  }
  const audio = new Float32Array(Math.ceil(seconds * SR));   // 표본값 = 말하는 사람들의 비트 합(1<<spk), 0은 침묵
  for (const x of turns) for (let i = Math.floor(x.t0 * SR); i < Math.min(audio.length, Math.floor(x.t1 * SR)); i++) audio[i] = audio[i] | (1 << x.spk);
  return { turns, audio };
}
const PS = [[], [0], [1], [2], [0, 1], [0, 2], [1, 2]];
function fakeSeg(labelStyle) {
  const id2label = labelStyle === 'names' ? { 0: 'NO_SPEAKER', 1: 'SPEAKER_0', 2: 'SPEAKER_1', 3: 'SPEAKER_2', 4: 'SPEAKER_0+SPEAKER_1', 5: 'SPEAKER_0+SPEAKER_2', 6: 'SPEAKER_1+SPEAKER_2' } : undefined;
  const proc = async part => ({ part });
  const model = async ({ part }) => {
    const nf = Math.floor(part.length / (FR * SR)), local = new Map(), rows = [];
    for (let f = 0; f < nf; f++) {
      const code = part[Math.floor((f + 0.5) * FR * SR)] | 0, who = [];
      for (let s = 0; s < 8; s++) if (code & (1 << s)) { if (!local.has(s) && local.size < 3) local.set(s, local.size); if (local.has(s)) who.push(local.get(s)); }
      who.sort(); const set = who.slice(0, 2); const id = PS.findIndex(p => p.length === set.length && p.every((v, k) => v === set[k]));
      rows.push(Array.from({ length: 7 }, (_, k) => k === id ? 5 : 0));
    }
    return { logits: { tolist: () => [rows] } };
  };
  model.config = { id2label };
  return { model, proc };
}
function fakeEmbedder(nSpk, noise = 0.03) {
  const D = 256, base = Array.from({ length: nSpk }, () => { const v = Float32Array.from({ length: D }, gauss); const n = Math.hypot(...v); return v.map(x => x / n); });
  return async buf => {
    const cnt = new Array(nSpk).fill(0); for (let i = 0; i < buf.length; i += 5) { const c = buf[i] | 0; for (let s = 0; s < nSpk; s++) if (c === (1 << s)) cnt[s]++; }
    const s = cnt.indexOf(Math.max(...cnt)); const v = base[s].map(x => x + gauss() * noise); const n = Math.hypot(...v); return v.map(x => x / n);
  };
}
function wordsFor(truth) {   // 0.35초마다 한 단어(겹친 짧은 맞장구는 인식되지 않았다고 본다)
  const w = []; for (const x of truth.turns) { if (x.backchannel) continue; for (let t = x.t0; t + 0.3 <= x.t1; t += 0.35) w.push({ t0: t, t1: t + 0.3, text: ' w', truth: x.spk }); }
  return w.sort((p, q) => p.t0 - q.t0);
}
function score(words, segs) {   // 단어마다 결과 문단의 화자 → 정답 화자와 가장 많이 겹치는 1:1 대응으로 정확도
  const hyp = words.map(w => { const g = segs.find(s => w.t0 >= s.t0 - 1e-6 && w.t0 <= s.t1 + 1e-6); return g ? g.spk : '?'; });
  const pairs = new Map(); words.forEach((w, i) => { const k = hyp[i] + '|' + w.truth; pairs.set(k, (pairs.get(k) || 0) + 1); });
  const used = new Set(), usedT = new Set(); let ok = 0;
  for (const [k, n] of [...pairs].sort((p, q) => q[1] - p[1])) { const [h, t] = k.split('|'); if (used.has(h) || usedT.has(t)) continue; used.add(h); usedT.add(t); ok += n; }
  return { acc: ok / words.length, nHyp: new Set(hyp).size };
}
async function run(name, { nSpk, seconds, labelStyle, numSpeakers = 0, maxSpeakers = 0, noise, expectSpk, minAcc }) {
  seed = 11 + nSpk * 3 + seconds;
  const truth = makeTruth(nSpk, seconds), { model, proc } = fakeSeg(labelStyle);
  T.set(model, proc, fakeEmbedder(nSpk, noise));
  logs.length = 0;
  const found = await T.findTurns(truth.audio, SR, 'window');
  const turns = await T.unifyAny(truth.audio, SR, found, numSpeakers, maxSpeakers);
  const words = wordsFor(truth), segs = T.assignWords(words.map(w => ({ t0: w.t0, t1: w.t1, text: w.text })), turns, true);
  const r = score(words, segs), pass = r.acc >= minAcc && (expectSpk == null || r.nHyp === expectSpk);
  console.log(`${pass ? 'OK  ' : 'FAIL'} ${name}: 화자 ${r.nHyp}명(정답 ${nSpk}) · 단어 화자 정확도 ${(r.acc * 100).toFixed(1)}% · 창 단위 ${found.units.length}개 · ${logs.filter(l => l.includes('화자 통일')).join(' ')}`);
  return pass;
}
function testSmoothing() {
  const w = (t0, spk) => ({ t0, t1: t0 + 0.25, text: ' x', spk });
  const turns = [{ t0: 0, t1: 1.0, spk: 'A' }, { t0: 1.0, t1: 1.3, spk: 'B' }, { t0: 1.3, t1: 3, spk: 'A' }, { t0: 4, t1: 4.4, spk: 'B' }, { t0: 5, t1: 7, spk: 'A' }];
  const words = [0, 0.3, 0.6, 1.02, 1.3, 1.6, 4.05, 5.1, 5.4].map(t => w(t));
  const on = T.assignWords(words, turns, true), off = T.assignWords(words, turns, false);
  // 켜면: 1.02의 끼인 한 단어는 A로 흡수, 4.05의 "쉬었다가 한 대답"은 B로 남는다 → 문단 3개(A, B, A). 끄면 5개
  const pass = on.length === 3 && on[1].spk !== on[0].spk && off.length === 5;
  console.log(`${pass ? 'OK  ' : 'FAIL'} 짧은 끼임 정리: 켬 ${on.length}문단 · 끔 ${off.length}문단`);
  return pass;
}
function testFrameLabels() {
  const L = { 0: 'NO_SPEAKER', 1: 'SPEAKER_0', 2: 'SPEAKER_1', 3: 'SPEAKER_2', 4: 'SPEAKER_0+SPEAKER_1' };
  const ctx2 = {}; vm.createContext(ctx2); vm.runInContext(src.slice(src.indexOf('const POWERSET'), src.indexOf('async function segmentWindows')) + ';globalThis.f = frameSets;', ctx2);
  const rows = [[9, 0, 0, 0, 0, 0, 0], [0, 9, 0, 0, 0, 0, 0], [0, 0, 0, 0, 9, 0, 0], [0, 0, 0, 0, 0, 0, 9]];
  const a1 = JSON.stringify(ctx2.f(rows, L)), a2 = JSON.stringify(ctx2.f(rows, {}));
  const pass = a1 === '[[],[0],[0,1],[1,2]]' && a2 === '[[],[0],[0,1],[1,2]]';
  console.log(`${pass ? 'OK  ' : 'FAIL'} 프레임 라벨 해석: ${a1} / ${a2}`);
  return pass;
}
(async () => {
  const res = [testFrameLabels(), testSmoothing()];
  res.push(await run('2명 · 3분', { nSpk: 2, seconds: 180, expectSpk: 2, minAcc: 0.95 }));
  res.push(await run('4명 · 10분(라벨 이름형)', { nSpk: 4, seconds: 600, labelStyle: 'names', expectSpk: 4, minAcc: 0.95 }));
  res.push(await run('6명 · 10분', { nSpk: 6, seconds: 600, expectSpk: 6, minAcc: 0.93 }));
  res.push(await run('5명 · 지정 5명 · 잡음 큼', { nSpk: 5, seconds: 400, numSpeakers: 5, noise: 0.05, expectSpk: 5, minAcc: 0.9 }));
  res.push(await run('3명 · 짧은 녹음 20초', { nSpk: 3, seconds: 20, minAcc: 0.9 }));
  res.push(await run('4명 · 40분(단위 700개 넘음)', { nSpk: 4, seconds: 2400, expectSpk: 4, minAcc: 0.95 }));
  const ok = res.every(Boolean);
  console.log('RESULT:', ok ? 'OK' : 'FAIL');
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
