#!/usr/bin/env bash
# GitHub 저장소 생성 + 첫 push + Pages 활성화 (GitHub CLI 필요: https://cli.github.com)
# 사용: ./publish.sh <저장소이름> [public|private]
set -e
NAME="${1:-meetnote}"; VIS="${2:-public}"
cd "$(dirname "$0")"
command -v gh >/dev/null || { echo "gh(GitHub CLI)가 필요해요. 설치 후 'gh auth login'을 먼저 실행하세요."; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login
[ -d .git ] || git init -b main
git add . && git commit -m "MeetNote: 초기 배포" >/dev/null 2>&1 || true
gh repo create "$NAME" --"$VIS" --source=. --push
OWNER=$(gh api user -q .login)
gh api -X POST "repos/$OWNER/$NAME/pages" -f build_type=workflow >/dev/null 2>&1 || true
echo
echo "완료. 1~2분 뒤 https://$OWNER.github.io/$NAME/ 에서 열립니다."
echo "Google 로그인을 쓰려면 Cloud Console의 '승인된 JavaScript 원본'에 https://$OWNER.github.io 를 추가하고 web/config.js에 클라이언트 ID를 넣은 뒤 git push 하세요."
