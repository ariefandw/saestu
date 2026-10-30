# Multi-stage build: Go server (static) + Python/MediaPipe untuk estimasi tinggi badan dari kamera
FROM golang:1.26-alpine AS builder

WORKDIR /app

# Install git and ca-certificates
RUN apk add --no-cache git ca-certificates tzdata

# Cache go modules
COPY go.mod go.sum ./
RUN go mod download

# Copy source code and build statically linked binary
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o saestu-server .

# Runtime: Debian slim (MediaPipe tidak punya wheel untuk Alpine/musl)
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates tzdata libgl1 libegl1 libgles2 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /app/uploads /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Model pose dibake ke image supaya tidak download tiap container restart
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task', '/app/pose_landmarker_full.task')"

COPY estimate_length.py .
COPY --from=builder /app/saestu-server /app/saestu-server

# Default environment
ENV PORT=8080
ENV TZ=Asia/Jakarta
ENV PYTHON_BIN=python
ENV DB_PATH=/app/data/saestu_iot.db
ENV UPLOAD_DIR=/app/uploads

EXPOSE 8080

# Persist database and uploads
VOLUME ["/app/uploads", "/app/data"]

ENTRYPOINT ["/app/saestu-server"]
