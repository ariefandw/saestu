# Multi-stage build for ultra-small, secure production image
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

# Final minimal production container
FROM alpine:3.20

WORKDIR /app

RUN apk add --no-cache ca-certificates tzdata && \
    mkdir -p /app/uploads /app/data

# Copy binary from builder
COPY --from=builder /app/saestu-server /app/saestu-server

# Default environment
ENV PORT=8080
ENV TZ=Asia/Jakarta

EXPOSE 8080

# Persist database and uploads
VOLUME ["/app/uploads", "/app/data"]

ENTRYPOINT ["/app/saestu-server"]
