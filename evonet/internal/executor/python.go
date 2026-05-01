package executor

import (
	"bytes"
	"context"
	"encoding/json"
	"os/exec"
	"time"
)

type execPythonParams struct {
	Code    string            `json:"code"`
	Timeout int               `json:"timeout"`
	Env     map[string]string `json:"env"`
	Cwd     string            `json:"cwd"`
}

func (e *Executor) handleExecPython(req Request) Response {
	var p execPythonParams
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

	cmd := exec.CommandContext(ctx, "python3", "-")
	cmd.Dir = cwd
	cmd.Stdin = bytes.NewBufferString(p.Code)

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
				Stderr:        "Execution timed out",
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
