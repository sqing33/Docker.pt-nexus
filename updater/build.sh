#!/bin/bash

echo "Building updater..."
CGO_ENABLED=0 go build -ldflags="-s -w" -o updater updater.go
echo "Build complete: updater"
