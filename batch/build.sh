#!/bin/bash

echo "Building batch..."
echo " - linux/amd64 -> batch-x86"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o batch-x86 batch.go || exit 1

echo " - linux/arm64 -> batch-arm"
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags="-s -w" -o batch-arm batch.go || exit 1

# 兼容历史路径：保留 batch/batch（默认使用 x86 版本）
cp -f batch-x86 batch || exit 1

echo "Build complete: batch-x86, batch-arm (and batch)"
