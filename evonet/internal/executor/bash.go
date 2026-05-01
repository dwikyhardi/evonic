package executor

import (
	"bytes"
	"context"
	"encoding/json"
	"os/exec"
	"time"
)

type execBashParams struct {
	Script  string            `json:"script"`
	Timeout int               `json:"timeout"`
	Env     map[string]string `json:"env"`
	Cwd     string            `json:"cwd"`
}

type execResult struct {
	Stdout        string  `json:"stdout"`
	Stderr        string  `json:"stderr"`
	ExitCode      int     `json:"exit_code"`
	ExecutionTime float64 `json:"execution_time"`
}

const maxOutputBytes = 64 * 1024 // 64 KB

func truncate(s string) string {
	if len(s) <= maxOutputBytes {
		return s
	}
	return s[:maxOutputBytes] + "\n[truncated]"
}

func (e *Executor) handleExecBash(req Request) Response {
	var p execBashParams
	if err := json.Unmarshal(req.Params, &p); err != nil {
		return errResp(req.ID, "invalid params: "+err.Error())
	}
	timeout := p.Timeout
	if timeout <= 0 || timeout > 600 {
		timeout = 60
	}
	cwd := p.Cwd
	if cwd == "" {
		cwd = e.workDir
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "bash", "-s")
	cmd.Dir = cwd
	cmd.Stdin = bytes.NewBufferString(p.Script)

	// Build environment
	var envPairs []string
	for k, v := range p.Env {
		envPairs = append(envPairs, k+"="+v)
	}
	if len(envPairs) > 0 {
		cmd.Env = append(cmd.Environ(), envPairs...)
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	t0 := time.Now()
	exitCode := 0
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return okResp(req.ID, execResult{
				Stderr:        "Execution timed out after " + string(rune('0'+timeout)) + "s",
				ExitCode:      -1,
				ExecutionTime: time.Since(t0).Seconds(),
			})
		}
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			exitCode = -1
		}
	}
	elapsed := time.Since(t0).Seconds()
	return okResp(req.ID, execResult{
		Stdout:        truncate(stdout.String()),
		Stderr:        truncate(stderr.String()),
		ExitCode:      exitCode,
		ExecutionTime: elapsed,
	})
}
