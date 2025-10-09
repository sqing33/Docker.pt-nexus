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

WORKDIR /app/batch-enhancer

COPY ./batch-enhancer/go.mod ./

RUN go mod download

COPY ./batch-enhancer/main.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o batch-enhancer main.go

# Stage 3: Final runtime
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies first
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    mediainfo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements and install
COPY ./server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY ./server ./

# Copy built frontend
COPY --from=builder /app/webui/dist ./dist

# Copy Go batch enhancer
COPY --from=go-builder /app/batch-enhancer/batch-enhancer ./batch-enhancer
RUN chmod +x ./batch-enhancer

# Copy startup script
COPY ./start-services.sh ./start-services.sh
RUN chmod +x ./start-services.sh

# Create data directory
RUN mkdir -p /app/data

VOLUME /app/data

EXPOSE 5272
EXPOSE 5275

CMD ["./start-services.sh"]
