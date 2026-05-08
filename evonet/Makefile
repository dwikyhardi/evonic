# Evonet Makefile

BINARY  := evonet
GO      := go
GOFLAGS := -trimpath -ldflags="-s -w"
# GUI Windows build hides the console window (no terminal popup on double-click)
GOFLAGS_WIN_GUI := -trimpath -ldflags="-s -w -H windowsgui"
DIST    := dist

.PHONY: build build-linux build-windows build-macos build-all \
        build-gui-windows build-gui-macos clean embed test

## Build for current platform (output: dist/evonet)
build:
	mkdir -p $(DIST)
	$(GO) build $(GOFLAGS) -o $(DIST)/$(BINARY) .

## Build CLI binary for Linux (amd64) — full GUI included (Fyne + CGo work natively on Linux).
build-linux:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 $(GO) build $(GOFLAGS) -o $(DIST)/$(BINARY)-linux-amd64 .

## Build CLI binary for macOS (arm64 + amd64) — headless / no GUI.
## Uses -tags headless so it compiles on Linux without macOS CGo/OpenGL headers.
## For a real GUI .app build, run build-gui-macos on a Mac.
build-macos:
	mkdir -p $(DIST)
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 $(GO) build $(GOFLAGS) -tags headless -o $(DIST)/$(BINARY)-darwin-arm64 .
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 $(GO) build $(GOFLAGS) -tags headless -o $(DIST)/$(BINARY)-darwin-amd64 .

## Build CLI binary for Windows (amd64) — headless / no GUI.
## Uses -tags headless so it compiles on Linux without mingw-w64 CGo toolchain.
## For a GUI binary (with hidden console), use build-gui-windows (fyne-cross) or
## build-gui-windows-native (requires mingw-w64).
build-windows:
	mkdir -p $(DIST)
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 $(GO) build $(GOFLAGS) -tags headless -o $(DIST)/$(BINARY)-windows-amd64.exe .

## Build all platforms into dist/
build-all: build-linux build-macos build-windows

## Build GUI binary for Windows (hides console window; requires fyne-cross + Docker)
## Install fyne-cross: go install fyne.io/fyne/v2/cmd/fyne-cross@latest
build-gui-windows:
	mkdir -p $(DIST)
	fyne-cross windows -arch amd64 -output $(BINARY)-windows-amd64.exe .
	mv fyne-cross/dist/windows-amd64/$(BINARY)-windows-amd64.exe.zip $(DIST)/ 2>/dev/null || true

## Build GUI binary for Windows without Docker (cross-compile from Linux, requires mingw-w64)
build-gui-windows-native:
	mkdir -p $(DIST)
	CGO_ENABLED=1 CC=x86_64-w64-mingw32-gcc \
	GOOS=windows GOARCH=amd64 \
	$(GO) build $(GOFLAGS_WIN_GUI) -o $(DIST)/$(BINARY)-windows-amd64.exe .

## Build GUI .app bundle for macOS — run ON a Mac (requires Xcode CLI tools + fyne)
## go install fyne.io/fyne/v2/cmd/fyne@latest
FYNE := $(shell $(GO) env GOPATH)/bin/fyne
build-gui-macos:
	mkdir -p $(DIST)
	$(FYNE) package --target darwin --name Evonet --app-id com.evonic.evonet --icon Icon.png 2>/dev/null || \
	$(FYNE) package --target darwin --name Evonet --app-id com.evonic.evonet
	mv Evonet.app $(DIST)/Evonet.app
	@echo "Built: $(DIST)/Evonet.app"

## Embed a config.json into a binary: make embed BINARY=dist/evonet-linux-amd64 CONFIG=myconfig.json
embed:
	./scripts/embed_config.sh $(BINARY) $(CONFIG)

## Run tests
test:
	$(GO) test ./...

clean:
	rm -rf $(DIST)
