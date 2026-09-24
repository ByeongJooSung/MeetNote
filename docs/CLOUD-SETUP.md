# Google 로그인 · 클라우드 저장 설정

MeetNote는 서버 없이 동작합니다. 클라우드 저장은 아래처럼 나뉩니다.

| 무엇 | 어디에 | 비용 |
|---|---|---|
| 회의록 파일(.mnote, 녹음 포함) | **각 사용자의 Google Drive** `MeetNote` 폴더 | 없음(사용자 Drive 용량 사용) |
| 목록(제목·일시·길이·Drive 파일 id) | **Firestore** `users/{uid}/meetings/{회의 id}` | 무료 한도 안(문서 1건 ≈ 0.3KB) |
| 내 설정(분석 방식·PC 서비스 주소·AI 엔진 주소 등, 토큰 제외) | **Firestore** `users/{uid}/settings/prefs` | 위와 같음. 규칙에 이 경로가 없으면 브라우저에만 기억 |
| 프로젝트(이름·설명·참고 문서·통합 참조 문서·구성원) | **Firestore** `projects/{id}` (소유자 uid + memberEmails) | 소유자와 초대된 이메일(같은 Google 계정으로 로그인)만 읽고 쓴다. 규칙에 없으면 브라우저에만 저장 |
| 프로젝트 회의록 목록 | **Firestore** `projects/{id}/meetings/{mid}` | 구성원이 각자 올린 회의록의 제목·일시·Drive 파일 id. 파일은 올린 사람의 Drive에 있고 구성원에게 Drive 권한(편집)으로 공유된다(알림 메일 없음) |
| 로그인 | Google Identity Services + Firebase Auth | 없음 |

- 앱은 `drive.file` 권한만 씁니다. **이 앱이 만든 파일만** 볼 수 있고, 사용자의 다른 Drive 파일은 볼 수 없습니다.
- Firestore를 설정하지 않아도 됩니다. 그러면 목록도 Drive에서 읽습니다(Drive가 원본, Firestore는 색인).
- 아래 값(클라이언트 ID, Firebase apiKey·projectId)은 공개돼도 되는 식별자입니다. 데이터 보호는 Google 계정 인증과 Firestore 보안 규칙이 맡습니다.

> 정적 사이트라 "로그인 화면"은 화면 잠금일 뿐입니다(소스를 내려받아 실행하면 앱 화면은 볼 수 있음). 하지만 **데이터는 본인 Google 계정으로 인증해야만** 읽고 쓸 수 있어, 다른 사람의 회의록에는 접근할 수 없습니다.

## 1. Firebase 프로젝트 만들기 (Google Cloud 프로젝트가 함께 생깁니다)
1. https://console.firebase.google.com → **프로젝트 추가** (이름 예: `meetnote`). 애널리틱스는 꺼도 됩니다. 요금제는 **Spark(무료)** 그대로 둡니다.
2. **빌드 → Authentication → 시작하기 → 로그인 방법 → Google → 사용 설정**. 지원 이메일을 고르고 저장.
3. **Authentication → 설정 → 승인된 도메인**에 배포 도메인(예: `byeongjoosung.github.io`)을 추가. `localhost`는 기본으로 들어 있습니다.
4. **빌드 → Firestore Database → 데이터베이스 만들기** → 위치 `asia-northeast3`(서울) → **프로덕션 모드**.
5. Firestore **규칙** 탭에 아래를 붙여 넣고 **게시**:
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       // 본인 목록만 읽고 쓸 수 있음 + 정해진 항목·길이만 허용(남용 방지)
       match /users/{uid}/meetings/{id} {
         allow read, delete: if request.auth != null && request.auth.uid == uid;
         allow create, update: if request.auth != null && request.auth.uid == uid
           && request.resource.data.keys().hasOnly(['title','when','duration','bytes','updatedAt','fileId','name','project','projectName'])
           && request.resource.data.title is string && request.resource.data.title.size() <= 200
           && request.resource.data.fileId is string && request.resource.data.fileId.size() <= 200
           && (!('name' in request.resource.data) || (request.resource.data.name is string && request.resource.data.name.size() <= 300));
       }
       // 프로젝트(회의록 묶음 + 참고 문서 통합본 + 구성원). 소유자와 memberEmails에 든 사람만 읽고 쓴다
       function projMember(data) { return request.auth != null && (data.owner == request.auth.uid || request.auth.token.email in data.memberEmails); }
       match /projects/{pid} {
         allow read: if projMember(resource.data);
         allow create: if request.auth != null && request.resource.data.owner == request.auth.uid
           && request.resource.data.keys().hasOnly(['json','name','updatedAt','deleted','owner','ownerEmail','memberEmails'])
           && request.resource.data.json is string && request.resource.data.json.size() <= 400000;
         allow update: if projMember(resource.data) && request.resource.data.owner == resource.data.owner
           && request.resource.data.keys().hasOnly(['json','name','updatedAt','deleted','owner','ownerEmail','memberEmails'])
           && request.resource.data.json is string && request.resource.data.json.size() <= 400000;
         allow delete: if request.auth != null && resource.data.owner == request.auth.uid;
         // 프로젝트에 묶인 회의록 목록(구성원이 각자 올린 것). 파일 자체는 올린 사람의 Drive에 있고 구성원에게 공유된다
         match /meetings/{mid} {
           allow read, write: if projMember(get(/databases/$(database)/documents/projects/$(pid)).data);
         }
       }
       // 옛 위치(개인 프로젝트). 앱이 처음 로그인할 때 위 projects로 옮긴 뒤에는 쓰지 않는다 — 옮긴 뒤 지워도 된다
       match /users/{uid}/projects/{id} {
         allow read, delete: if request.auth != null && request.auth.uid == uid;
         allow create, update: if request.auth != null && request.auth.uid == uid
           && request.resource.data.keys().hasOnly(['json','name','updatedAt','deleted'])
           && request.resource.data.json is string && request.resource.data.json.size() <= 400000
           && request.resource.data.name is string && request.resource.data.name.size() <= 100;
       }
       // 내 설정 동기화(발언자 분석 방식·PC 서비스 주소·발언자 수, AI 엔진 주소·모델 등. 토큰·키는 저장하지 않음)
       match /users/{uid}/settings/{doc} {
         allow read, delete: if request.auth != null && request.auth.uid == uid;
         allow create, update: if request.auth != null && request.auth.uid == uid
           && request.resource.data.keys().hasOnly(['json','updatedAt'])
           && request.resource.data.json is string && request.resource.data.json.size() <= 40000
           && request.resource.data.updatedAt is string && request.resource.data.updatedAt.size() <= 40;
       }
     }
   }
   ```
6. **프로젝트 설정(톱니) → 일반**에서 **웹 API 키**와 **프로젝트 ID**를 적어 둡니다. ("내 앱"에 웹 앱을 등록하지 않아도 API 키는 보입니다. 안 보이면 웹 앱(</>)을 하나 등록하세요.)

## 2. OAuth 클라이언트 · Drive API (같은 프로젝트의 Google Cloud Console)
1. https://console.cloud.google.com 에서 위에서 만든 프로젝트를 고릅니다.
2. **API 및 서비스 → 라이브러리 → Google Drive API → 사용**.
3. **API 및 서비스 → OAuth 동의 화면**
   - 사용자 유형 **외부**, 앱 이름 `MeetNote`, 지원 이메일 입력.
   - **범위 추가**: `.../auth/drive.file` (Google Drive에서 이 앱으로 만든 파일만). 민감하지 않은 범위라 별도 심사가 필요 없습니다.
   - 처음에는 **테스트** 상태입니다(테스트 사용자로 등록한 계정만 로그인 가능, 최대 100명). 누구나 쓰게 하려면 **앱 게시(프로덕션)** 를 누릅니다.
4. **API 및 서비스 → 사용자 인증 정보** → Firebase가 만든 **"Web client (auto created by Google Service)"** 를 엽니다(없으면 *사용자 인증 정보 만들기 → OAuth 클라이언트 ID → 웹 애플리케이션*).
   - **승인된 JavaScript 원본**에 추가: `https://byeongjoosung.github.io` (경로 없이), 로컬 테스트용 `http://localhost:8080`
   - 리디렉션 URI는 필요 없습니다.
   - **클라이언트 ID**(`…apps.googleusercontent.com`)를 복사합니다.
   > 직접 새로 만든 클라이언트라면 Firebase **Authentication → 로그인 방법 → Google → 외부 프로젝트의 클라이언트 ID 허용 목록**에 그 ID를 추가해야 목록 DB 로그인이 됩니다. Firebase가 자동으로 만든 클라이언트를 쓰면 이 단계가 필요 없습니다.

## 3. `web/config.js`에 값 넣기
```js
window.MEETNOTE_CONFIG = {
  googleClientId: "1234567890-xxxx.apps.googleusercontent.com",
  requireLogin: true,
  firebase: { apiKey: "AIza...", projectId: "meetnote-xxxxx" }
};
```
`git push` 하면 1~2분 뒤 배포됩니다. `googleClientId`가 들어가면 **Google 로그인 없이는 앱을 열 수 없고**, 브라우저에 저장된 설정으로 이를 끌 수 없습니다.

### API 키 제한(권장)
Google Cloud Console → **사용자 인증 정보 → API 키(Browser key)** → **웹사이트 제한**에 `https://byeongjoosung.github.io/*`, `http://localhost:8080/*` 를 넣고, **API 제한**은 *Identity Toolkit API*, *Token Service API*, *Cloud Firestore API*만 허용합니다.

## 4. 쓰는 방법
- **☁ 클라우드 저장**: 처음 한 번 Drive 권한 창이 뜹니다(“이 앱으로 만든 Drive 파일 보기·수정”). 같은 회의를 다시 저장하면 같은 파일을 덮어씁니다.
- **내 회의록**: 목록에서 열기·삭제. 삭제는 Drive **휴지통**으로 옮기므로 30일 안에 되살릴 수 있습니다.
- **Drive와 목록 맞추기**: Drive에서 직접 지웠거나 다른 기기에서 저장해 목록이 어긋났을 때, Drive 폴더를 기준으로 목록을 다시 맞춥니다.
- `.mnote로 저장`(파일 내려받기)은 그대로 쓸 수 있습니다.
- Drive 권한은 **⚙ 설정 → 계정·클라우드**에서 다시 연결하거나 해제할 수 있습니다. 구글 계정의 https://myaccount.google.com/permissions 에서도 언제든 끊을 수 있습니다.

## 보안 점검표 (공개 저장소로 운영할 때)
저장소에 들어 있는 값(클라이언트 ID, Firebase `apiKey`·`projectId`, 관리자 이메일)은 **비밀이 아니라 식별자**라서 공개돼도 됩니다. 웹 앱은 구조상 이 값들을 숨길 수 없고(브라우저가 내려받아야 동작), 보호는 아래 설정이 맡습니다.

| 항목 | 어디서 | 왜 |
|---|---|---|
| **API 키 제한** | Cloud Console(Firebase 프로젝트) → 사용자 인증 정보 → Browser key → 웹사이트 제한 `https://byeongjoosung.github.io/*` + API 제한(Identity Toolkit, Token Service, Cloud Firestore) | 다른 사이트가 내 키로 할당량을 쓰지 못하게 |
| **승인된 JavaScript 원본** | OAuth 클라이언트 | 다른 사이트가 내 클라이언트 ID로 로그인 창을 띄우지 못하게(이미 설정됨) |
| **Firestore 규칙** | 위 1-5의 규칙 | 본인 문서만, 정해진 항목만. 규칙이 없으면 누구나 읽고 쓸 수 있음 |
| **결제 수단 미등록(Spark 유지)** | Firebase 요금제 | 누가 남용해도 요금이 청구되지 않고 그날 한도에서 멈춤 |
| **Firebase 로그인 제공업체** | Authentication → 로그인 방법 | Google만 켜 두기(이메일/비밀번호·익명 로그인은 끄기) |
| **비밀 값 금지** | 저장소 전체 | OAuth *클라이언트 보안 비밀번호*, 서비스 계정 키(JSON), Anthropic API 키는 절대 커밋하지 않기(이 앱은 쓰지 않음) |

앱 쪽에서 이미 하는 것: 남이 만든 `.mnote`를 열 때 HTML·전사 데이터 검증(스크립트 차단), 외부 스크립트 무결성 검사(SRI)·버전 고정, Drive 토큰은 메모리에만 보관, 로컬 LLM 토큰은 기본으로 탭을 닫으면 삭제, 로그에 토큰·계정 식별자 미기록, 관리자 설정 화면은 관리자 계정에만 표시.
한계: 정적 사이트라 "관리자 표시"와 "로그인 화면"은 화면 제어일 뿐입니다. 데이터 접근 권한은 Google 계정 인증과 위 규칙이 결정합니다.

## 5. 무료 한도 참고 (2026년 기준, 바뀔 수 있음)
- Firestore(Spark): 저장 1GiB, 하루 읽기 5만·쓰기 2만·삭제 2만. 목록 문서만 저장하므로 회의 수십만 건까지 여유가 있습니다. 한도를 넘으면 그날 요청이 거절될 뿐 **요금이 청구되지 않습니다**(결제 수단을 등록하지 않는 한).
- Firebase Auth: Google 로그인 무료.
- Drive: 각 사용자의 Google 계정 용량(기본 15GB). 1시간 회의 ≈ 60MB.

## 문제 해결
| 증상 | 원인 / 해결 |
|---|---|
| 로그인 버튼이 안 보이거나 `origin_mismatch` | OAuth 클라이언트의 **승인된 JavaScript 원본**에 현재 주소가 없음 |
| `access_denied` / “앱이 확인되지 않음” | 동의 화면이 **테스트** 상태인데 테스트 사용자에 없는 계정. 계정을 추가하거나 앱을 게시 |
| 저장 시 “권한 창(팝업)이 막혔어요” | 브라우저 주소창의 팝업 차단 해제 후 다시 누르기 |
| “목록 DB에는 기록하지 못했어요” | Firebase 설정(API 키·프로젝트 ID·Google 로그인 사용 설정·허용 클라이언트 ID·규칙) 확인. 파일은 Drive에 저장돼 있으니 **Drive와 목록 맞추기**로 복구 |
| `INVALID_IDP_RESPONSE` / `audience` 오류 | 다른 프로젝트의 OAuth 클라이언트를 쓰는 중 → Firebase Google 로그인 설정의 허용 클라이언트 ID에 추가 |
| 자세한 원인 | **⚙ 설정 → 로그**에 HTTP 상태와 오류 본문이 남습니다 |
