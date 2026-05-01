//go:build !windows && !darwin

// Package gui is a no-op stub on non-desktop platforms (Linux, etc.).
package gui

import "github.com/evonic/evonet/internal/config"

// RunGUI is a no-op on Linux — caller falls back to headless mode.
func RunGUI(cfg *config.Config) {}

// ShowPairingDialog is a no-op on Linux.
func ShowPairingDialog(prefilledServerURL string) {}
