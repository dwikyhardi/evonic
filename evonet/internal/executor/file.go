package executor

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type readFileParams struct {
	Path string `json:"path"`
}

type writeFileParams struct {
	Path    string `json:"path"`
	Content string `json:"content"`
	Mode    string `json:"mode"` // "overwrite" (default) or "append"
}

func (e *Executor) handleReadFile(req Request) Response {
	var p readFileParams
	if err := json.Unmarshal(req.Params, &p); err != nil {
		return errResp(req.ID, "invalid params: "+err.Error())
	}
	path, err := resolvePath(p.Path, e.workDir)
	if err != nil {
		return errResp(req.ID, "read_file error: "+err.Error())
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return errResp(req.ID, "read_file error: "+err.Error())
	}
	return okResp(req.ID, map[string]any{
		"content": string(data),
		"size":    len(data),
		"path":    path,
	})
}

func (e *Executor) handleWriteFile(req Request) Response {
	var p writeFileParams
	if err := json.Unmarshal(req.Params, &p); err != nil {
		return errResp(req.ID, "invalid params: "+err.Error())
	}
	path, err := resolvePath(p.Path, e.workDir)
	if err != nil {
		return errResp(req.ID, "write_file error: "+err.Error())
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return errResp(req.ID, "mkdir error: "+err.Error())
	}
	flag := os.O_WRONLY | os.O_CREATE | os.O_TRUNC
	if p.Mode == "append" {
		flag = os.O_WRONLY | os.O_CREATE | os.O_APPEND
	}
	f, err := os.OpenFile(path, flag, 0644)
	if err != nil {
		return errResp(req.ID, "open error: "+err.Error())
	}
	defer f.Close()
	if _, err := f.WriteString(p.Content); err != nil {
		return errResp(req.ID, "write error: "+err.Error())
	}
	return okResp(req.ID, map[string]any{"ok": true, "path": path})
}

// resolvePath joins the requested path with workDir, cleans the result,
// and validates that the resolved path stays within workDir.
func resolvePath(path, workDir string) (string, error) {
	resolved := filepath.Join(workDir, path)
	clean := filepath.Clean(resolved)
	// Ensure trailing separator on workDir to prevent partial prefix match
	// (e.g. /home/user must not match /home/user2).
	prefix := workDir
	if !strings.HasSuffix(prefix, string(os.PathSeparator)) {
		prefix += string(os.PathSeparator)
	}
	if !strings.HasPrefix(clean, prefix) && clean != workDir {
		return "", fmt.Errorf("path escapes working directory: %s", path)
	}
	return clean, nil
}
