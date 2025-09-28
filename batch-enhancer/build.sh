#!/bin/bash

echo "Building batch enhancer..."
CGO_ENABLED=0 go build -ldflags="-s -w" -o batch-enhancer main.go
echo "Build complete: batch-enhancer"