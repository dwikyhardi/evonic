package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
)

// Magic marker appended before the embedded JSON config.
// Must not appear in normal Go binary content (uses null bytes as guards).
var embeddedMarker = []byte{0x00, 0x00, 'E', 'V', 'O', 'N', 'E', 'T', '_', 'C', 'F', 'G', 0x00, 0x00}

// ReadEmbedded reads the config JSON appended after the magic marker in the current binary.
// Returns an error if the marker is not found or the JSON is invalid.
func ReadEmbedded() (*Config, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(exe)
	if err != nil {
		return nil, err
	}
	idx := bytes.LastIndex(data, embeddedMarker)
	if idx < 0 {
		return nil, errors.New("no embedded config marker found")
	}
	jsonData := data[idx+len(embeddedMarker):]
	// Trim trailing nulls or whitespace
	jsonData = bytes.TrimRight(jsonData, "\x00\r\n\t ")
	if len(jsonData) == 0 {
		return nil, errors.New("embedded config is empty")
	}
	var cfg Config
	if err := json.Unmarshal(jsonData, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
