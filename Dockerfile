# Stage 1: Build Vue frontend
FROM node:20-alpine AS builder

WORKDIR /app/vue3

RUN npm install -g pnpm

COPY ./vue3/package.json ./vue3/pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

COPY ./vue3 .

RUN pnpm build

# Stage 2: Setup Python application
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY --from=builder /app/vue3/dist ./dist

COPY ./flask/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY ./flask .

VOLUME /app/data

EXPOSE 5272

CMD ["python", "app.py"]
