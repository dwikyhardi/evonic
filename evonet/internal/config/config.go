// Package config provides layered configuration for Evonet.
//
// Priority (highest wins): CLI flags > config.yaml > embedded config.
package config

import (
	"os"
	"runtime"

	"gopkg.in/yaml.v3"
)

// Config holds all Evonet settings.
type Config struct {
	// Required: set after pairing
	ConnectorToken string `yaml:"connector_token" json:"connector_token"`
	HomeID         string `yaml:"home_id"         json:"home_id"`
	HomeName       string `yaml:"home_name"       json:"home_name"`

	// Server endpoint (without trailing slash)
	ServerURL string `yaml:"server_url" json:"server_url"`

	// WebSocket port for the connector relay on the server
	WSPort int `yaml:"ws_port" json:"ws_port"`

	// Optional working directory; defaults to the directory of the Evonet binary
	WorkDir string `yaml:"work_dir" json:"work_dir"`
}

// Load reads layered config: embedded (in binary) → config.yaml → applied CLI overrides.
func Load(yamlPath string) (*Config, error) {
	// Start with embedded config (appended to binary)
	cfg, err := ReadEmbedded()
	if err != nil {
		// No embedded config: start with empty
		cfg = &Config{}
	}

	// Override with config.yaml if present
	if yamlPath != "" {
		if data, err := os.ReadFile(yamlPath); err == nil {
			var fileCfg Config
			if err2 := yaml.Unmarshal(data, &fileCfg); err2 == nil {
				applyOverride(cfg, &fileCfg)
			}
		}
	} else {
		// Try platform config dir by default
		if dir, err2 := configDir(); err2 == nil {
			defaultPath := dir + "/config.yaml"
			if data, err3 := os.ReadFile(defaultPath); err3 == nil {
				var fileCfg Config
				if err4 := yaml.Unmarshal(data, &fileCfg); err4 == nil {
					applyOverride(cfg, &fileCfg)
				}
			}
		}
	}

	return cfg, nil
}

// ApplyCLI applies CLI flag overrides onto a loaded Config.
func ApplyCLI(cfg *Config, flags CLIFlags) {
	if flags.ServerURL != "" {
		cfg.ServerURL = flags.ServerURL
	}
	if flags.Token != "" {
		cfg.ConnectorToken = flags.Token
	}
	if flags.WSPort != 0 {
		cfg.WSPort = flags.WSPort
	}
	if flags.WorkDir != "" {
		cfg.WorkDir = flags.WorkDir
	}
}

// CLIFlags represents command-line overrides.
type CLIFlags struct {
	ServerURL string
	Token     string
	WSPort    int
	WorkDir   string
}

// configDir returns the platform-appropriate config directory.
// Unix: $HOME/.config/evonet  Windows: %APPDATA%\evonet
func configDir() (string, error) {
	if runtime.GOOS == "windows" {
		appData := os.Getenv("APPDATA")
		if appData == "" {
			home, err := os.UserHomeDir()
			if err != nil {
				return "", err
			}
			appData = home
		}
		return appData + `\evonet`, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return home + "/.config/evonet", nil
}

// Save writes the config to the platform config dir.
func Save(cfg *Config) error {
	dir, err := configDir()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return err
	}
	return os.WriteFile(dir+"/config.yaml", data, 0600)
}

func applyOverride(base, override *Config) {
	if override.ConnectorToken != "" {
		base.ConnectorToken = override.ConnectorToken
	}
	if override.HomeID != "" {
		base.HomeID = override.HomeID
	}
	if override.HomeName != "" {
		base.HomeName = override.HomeName
	}
	if override.ServerURL != "" {
		base.ServerURL = override.ServerURL
	}
	if override.WSPort != 0 {
		base.WSPort = override.WSPort
	}
	if override.WorkDir != "" {
		base.WorkDir = override.WorkDir
	}
}
