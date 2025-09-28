# Stage 1: Build Vue frontend
FROM node:20-alpine AS builder

WORKDIR /app/webui

RUN npm install -g pnpm

COPY ./webui/package.json ./webui/pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

COPY ./webui .

RUN pnpm build

# Stage 2: Build Go batch enhancer
FROM golang:1.21-alpine AS go-builder

WORKDIR /app

COPY ./batch-enhancer-simple/go.mod ./
COPY ./batch-enhancer-simple/main.go ./

RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o batch-enhancer main.go

# Stage 3: Final runtime
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY --from=builder /app/webui/dist ./dist
COPY --from=go-builder /app/batch-enhancer ./batch-enhancer

COPY ./server/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY ./server .

RUN apt update && \
    apt install -y ffmpeg mediainfo && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Make batch enhancer executable
RUN chmod +x ./batch-enhancer

VOLUME /app/data

EXPOSE 5272
EXPOSE 9092

# Start script that runs both services
COPY ./start-services.sh .
RUN chmod +x ./start-services.sh

CMD ["./start-services.sh"]
