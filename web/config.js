// MeetNote 배포 설정. 이 파일만 고치면 됩니다. 설정 방법: docs/CLOUD-SETUP.md
// 여기 적는 값(클라이언트 ID, Firebase apiKey·projectId)은 공개돼도 되는 식별자입니다. 비밀 키는 넣지 마세요.
window.MEETNOTE_CONFIG = {
  // Google Cloud Console → API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트 ID(웹 애플리케이션)
  // "승인된 JavaScript 원본"에 배포 주소(예: https://아이디.github.io)와 http://localhost:8080 을 추가하세요.
  googleClientId: "622282166227-c7m54699gmk9j7q5pvmm92upqradhtrl.apps.googleusercontent.com",
  requireLogin: true,          // true: Google 로그인해야 앱 사용 가능(클라이언트 ID를 넣으면 브라우저에서 끌 수 없음)
  adminEmails: ["tjdqudwn@gmail.com"],   // 관리자 전용 설정 화면을 볼 수 있는 계정(화면 표시용)

  // 클라우드 저장: 파일(.mnote)은 각 사용자의 Google Drive에, 목록은 Firestore에 기록합니다.
  // 비워 두면 목록도 Drive에서 읽습니다(목록 DB 없이 동작).
  firebase: {
    apiKey: "AIzaSyCWluB9FYIfrfG5DTBgqgKuY1Diubkv7_I",   // Firebase 콘솔 → 프로젝트 설정 → 일반 → 웹 API 키
    projectId: "meetnote-1c25a"   // Firebase 프로젝트 ID
  },

  // 공유받은 회의록 열기(Google 파일 선택창)용 API 키. Google Picker API를 사용 설정한 프로젝트의 브라우저 키.
  // 비우면 firebase.apiKey를 씁니다. 프로젝트 번호는 googleClientId 앞의 숫자를 쓰며, 다르면 googleAppId: "번호" 를 넣으세요.
  pickerKey: "AIzaSyB9awVQZfT6JfGFjklfdhCoWY1V5c5ZlT0"
};
