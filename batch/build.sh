#!/bin/bash

echo "Building batch..."
CGO_ENABLED=0 go build -ldflags="-s -w" -o batch batch.go
echo "Build complete: batch"
