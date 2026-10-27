FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements-lock.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY models ./models
ENV MEDIASSIST_DB=/data/mediassist.db
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8010"]
