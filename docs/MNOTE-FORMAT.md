# .mnote 파일 형식

녹음과 회의록을 한 쌍으로 묶는 MeetNote 전용 형식. ZIP 컨테이너(.docx와 같은 방식)이며 모든 시간은 녹음 시작 기준 초 단위.

```
회의록.mnote
├─ mimetype          application/x-mnote+zip (첫 항목, 비압축)
├─ manifest.json     형식 버전(1.1), 제목, 일시, 길이, 오디오 경로, timing(recording|clock)
├─ audio/recording.* 녹음 원본 (webm/m4a/mp3/wav 등)
├─ notes.json        블록(문단·제목·목록·표)별 시점 t, HTML, 편집 기록 history, removed
├─ transcript.json   전사 구간 {t0, t1, text, spk?} · 파일에서 가져온 전사면 imported {src, kind, timed, name} (timed=false면 t0·t1은 순서용 가짜 시각)
├─ minutes.md        AI 회의록 초안 (있을 때)
├─ photos/photoN.jpg 회의 사진(붙임, 최대 4장, 긴 변 1600px JPEG) — manifest.json의 photos에 이름·크기
└─ notes.md          사람이 읽는 요약본
```

`notes.json`의 `history`는 블록이 바뀐 시점과 그때의 서식 포함 내용(HTML)을 차례로 담고 있어, 따라 쓰기 재생이 이 기록으로 글과 표를 다시 써 나갑니다. 1.0 형식(텍스트 메모) 파일도 그대로 열립니다.
