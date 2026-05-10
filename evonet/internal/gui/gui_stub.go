//go:build (!windows && !darwin) || headless

// Package gui is a no-op stub on non-desktop platforms (Linux, etc.)
// or when built with -tags headless (e.g. cross-compiling macOS/Windows from Linux).
package gui

import "github.com/evonic/evonet/internal/config"

// GUIAvailable returns false — this is the stub (headless / non-desktop).
func GUIAvailable() bool { return false }

// RunGUI is a no-op on Linux — caller falls back to headless mode.
func RunGUI(cfg *config.Config) {}

// ShowPairingDialog is a no-op on Linux.
func ShowPairingDialog(prefilledServerURL string) {}
