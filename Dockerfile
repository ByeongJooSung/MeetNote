# MeetNote 웹 + 발언자 구분 서버를 하나의 컨테이너로 (Render, Railway, Fly.io, 자체 서버)
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt && pip install --no-cache-dir resemblyzer --no-deps
COPY server server
COPY web web
ENV PORT=8765 OPEN_BROWSER=0 PRELOAD=1
EXPOSE 8765
CMD ["python", "server/diarize.py"]
