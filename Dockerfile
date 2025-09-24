# Stage 1: Build Vue frontend
FROM node:20-alpine AS builder

WORKDIR /app/webui

RUN npm install -g pnpm

COPY ./webui/package.json ./webui/pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

COPY ./webui .

RUN pnpm build

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY --from=builder /app/webui/dist ./dist

COPY ./server/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY ./server .

RUN apt update && \
    apt install -y ffmpeg mediainfo && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

VOLUME /app/data

EXPOSE 5272

CMD ["python", "app.py"]
