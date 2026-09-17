#!/usr/bin/env bash
# macOS/Linux: 이 폴더에서  ./install.sh  실행
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install resemblyzer --no-deps
command -v ffmpeg >/dev/null || echo "ffmpeg가 없어요. macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg"
echo "설치 완료. 실행:  python diarize.py"
