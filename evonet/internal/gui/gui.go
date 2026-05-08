//go:build (windows || darwin) && !headless

// Package gui provides the desktop GUI for Evonet.
// Only compiled on Windows and macOS (excluded when built with -tags headless).
package gui

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image/color"
	"io"
	"log"
	"net/http"
	"os"
	"runtime"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"

	"github.com/evonic/evonet/internal/config"
	"github.com/evonic/evonet/internal/executor"
	"github.com/evonic/evonet/internal/ws"
)

// GUIAvailable returns true — the real GUI is compiled in.
func GUIAvailable() bool { return true }

// RunGUI launches the connector window directly (config already available).
// Must be called from the main goroutine.
func RunGUI(cfg *config.Config) {
	a := app.New()
	w := a.NewWindow("Evonet")
	w.Resize(fyne.NewSize(700, 420))

	root := container.NewStack()
	w.SetContent(root)
	showConnectorView(a, w, root, cfg)

	w.ShowAndRun()
}

// ShowPairingDialog shows a pairing form first, then transitions to the connector view.
// Must be called from the main goroutine.
func ShowPairingDialog(prefilledServerURL string) {
	a := app.New()
	w := a.NewWindow("Evonet")
	w.Resize(fyne.NewSize(700, 420))

	root := container.NewStack()
	w.SetContent(root)
	showPairingView(a, w, root, prefilledServerURL)

	w.ShowAndRun()
}

// showConnectorView renders the log area with Stop/Start and Reset buttons.
// Creates its own LogWriter and wires window close. Safe to call from main goroutine.
func showConnectorView(a fyne.App, w fyne.Window, root *fyne.Container, cfg *config.Config) {
	logEntry := widget.NewMultiLineEntry()
	logEntry.Disable()
	logEntry.Wrapping = fyne.TextWrapWord
	logScroll := container.NewScroll(logEntry)
	lw := newLogWriter(logEntry, logScroll)

	log.SetOutput(lw)
	log.SetFlags(log.Ltime)

	statusLabel := widget.NewLabel("")
	statusLabel.Truncation = fyne.TextTruncateEllipsis

	connectedText := canvas.NewText("Connected.", color.RGBA{R: 0, G: 180, B: 0, A: 255})
	connectedText.TextSize = theme.TextSize()
	connectedText.Alignment = fyne.TextAlignLeading
	connectedText.Hide()

	toggleBtn := widget.NewButton("Stop", nil)
	toggleBtn.Importance = widget.DangerImportance

	resetBtn := widget.NewButton("Reset", nil)

	topBar := container.NewBorder(nil, nil, nil,
		container.NewHBox(resetBtn, toggleBtn),
		container.NewStack(statusLabel, container.NewPadded(connectedText)),
	)
	connectorView := container.NewBorder(topBar, nil, nil, nil, logScroll)

	root.Objects = []fyne.CanvasObject{connectorView}
	root.Refresh()

	var client *ws.Client
	var running bool

	startClient := func() {
		exec := executor.New(workDir(cfg), true) // GUI always verbose
		client = ws.New(cfg, exec)
		running = true
		connectedText.Hide()
		statusLabel.Show()
		statusLabel.SetText("Connecting to " + cfg.ServerURL + "...")
		toggleBtn.SetText("Stop")
		toggleBtn.Importance = widget.DangerImportance
		toggleBtn.Refresh()

		client.OnConnected = func() {
			fyne.Do(func() {
				statusLabel.Hide()
				connectedText.Show()
			})
		}
		client.OnDisconnected = func() {
			fyne.Do(func() {
				connectedText.Hide()
				statusLabel.Show()
				statusLabel.SetText("Connecting to " + cfg.ServerURL + "...")
			})
		}

		go func() {
			log.Printf("[evonet] Connecting to %s...", cfg.ServerURL)
			client.Run()
			fyne.Do(func() {
				running = false
				connectedText.Hide()
				statusLabel.Show()
				statusLabel.SetText("Stopped — click Start to reconnect")
				toggleBtn.SetText("Start")
				toggleBtn.Importance = widget.HighImportance
				toggleBtn.Refresh()
			})
		}()
	}

	toggleBtn.OnTapped = func() {
		if running {
			client.Stop()
		} else {
			startClient()
		}
	}

	resetBtn.OnTapped = func() {
		if client != nil {
			client.Stop()
		}
		lw.close()
		config.Save(&config.Config{}) //nolint — best-effort clear
		showPairingView(a, w, root, "")
	}

	w.SetOnClosed(func() {
		if client != nil {
			client.Stop()
		}
		lw.close()
	})

	startClient()
}

// showPairingView renders the pairing form into root. Must be called from main goroutine.
func showPairingView(a fyne.App, w fyne.Window, root *fyne.Container, prefilledServerURL string) {
	serverEntry := widget.NewEntry()
	serverEntry.SetPlaceHolder("https://your-evonic-server.com")
	if prefilledServerURL != "" {
		serverEntry.SetText(prefilledServerURL)
	}

	codeEntry := widget.NewEntry()
	codeEntry.SetPlaceHolder("X7KQ2M")

	statusLabel := widget.NewLabel("")
	statusLabel.Wrapping = fyne.TextWrapWord

	pairBtn := widget.NewButton("Pair & Connect", nil)
	pairBtn.Importance = widget.HighImportance

	form := &widget.Form{
		Items: []*widget.FormItem{
			{Text: "Server URL", Widget: serverEntry},
			{Text: "Pairing code", Widget: codeEntry},
		},
	}
	title := widget.NewLabelWithStyle("Evonet Setup", fyne.TextAlignCenter, fyne.TextStyle{Bold: true})

	pairingView := container.NewBorder(
		nil,
		container.NewPadded(container.NewVBox(pairBtn, statusLabel)),
		nil, nil,
		container.NewPadded(container.NewVBox(title, form)),
	)

	pairBtn.OnTapped = func() {
		serverURL := strings.TrimRight(strings.TrimSpace(serverEntry.Text), "/")
		code := strings.ToUpper(strings.TrimSpace(codeEntry.Text))

		if serverURL == "" || code == "" {
			statusLabel.SetText("Please fill in both fields.")
			return
		}

		pairBtn.Disable()
		statusLabel.SetText("Pairing...")

		go func() {
			cfg, err := doPair(serverURL, code)
			if err != nil {
				fyne.Do(func() {
					statusLabel.SetText("Error: " + err.Error())
					pairBtn.Enable()
				})
				return
			}
			if err := config.Save(cfg); err != nil {
				fyne.Do(func() {
					statusLabel.SetText("Paired but failed to save config: " + err.Error())
					pairBtn.Enable()
				})
				return
			}
			fyne.Do(func() {
				showConnectorView(a, w, root, cfg)
			})
		}()
	}

	root.Objects = []fyne.CanvasObject{pairingView}
	root.Refresh()
}

// doPair calls the Evonic pairing API and returns a populated Config on success.
func doPair(serverURL, code string) (*config.Config, error) {
	hostname, _ := os.Hostname()
	payload := map[string]string{
		"pairing_code": code,
		"device_name":  hostname,
		"platform":     runtime.GOOS,
		"version":      "1.0.0",
	}
	body, _ := json.Marshal(payload)

	resp, err := http.Post(serverURL+"/api/connector/pair", "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("server returned %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}

	var result struct {
		OK             bool   `json:"ok"`
		ConnectorToken string `json:"connector_token"`
		HomeID         string `json:"home_id"`
		HomeName       string `json:"home_name"`
		WSPort         int    `json:"ws_port"`
		Error          string `json:"error"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("invalid response: %w", err)
	}
	if !result.OK {
		return nil, fmt.Errorf("%s", result.Error)
	}

	return &config.Config{
		ServerURL:      serverURL,
		ConnectorToken: result.ConnectorToken,
		HomeID:         result.HomeID,
		HomeName:       result.HomeName,
		WSPort:         result.WSPort,
	}, nil
}

// workDir returns the directory of the running binary as the default work dir.
func workDir(cfg *config.Config) string {
	if cfg.WorkDir != "" {
		return cfg.WorkDir
	}
	exe, err := os.Executable()
	if err != nil {
		cwd, _ := os.Getwd()
		return cwd
	}
	for i := len(exe) - 1; i >= 0; i-- {
		if exe[i] == '/' || exe[i] == '\\' {
			return exe[:i]
		}
	}
	return "."
}
