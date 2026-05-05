package executor

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolvePath_NormalFile(t *testing.T) {
	wd := filepath.Clean("/home/user") + string(os.PathSeparator)
	got, err := resolvePath("foo.txt", wd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "/home/user/foo.txt"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestResolvePath_AbsolutePathGetsJoined(t *testing.T) {
	wd := filepath.Clean("/home/user") + string(os.PathSeparator)
	got, err := resolvePath("/etc/shadow", wd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Absolute paths are joined to workDir, not returned raw.
	want := "/home/user/etc/shadow"
	if got != want {
		t.Errorf("got %q, want %q (absolute path must be joined, not returned raw)", got, want)
	}
}

func TestResolvePath_TraversalEscape(t *testing.T) {
	wd := filepath.Clean("/home/user") + string(os.PathSeparator)
	_, err := resolvePath("../../../etc/shadow", wd)
	if err == nil {
		t.Fatal("expected error for traversal escape, got nil")
	}
}

func TestResolvePath_PartialPrefixMatch(t *testing.T) {
	wd := filepath.Clean("/home/user") + string(os.PathSeparator)
	// Absolute paths are joined to workDir, so /home/user2/secret becomes
	// /home/user/home/user2/secret — safely inside workDir, no error expected.
	got, err := resolvePath("/home/user2/secret", wd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "/home/user/home/user2/secret"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestResolvePath_WorkDirExact(t *testing.T) {
	wd := filepath.Clean("/home/user") + string(os.PathSeparator)
	got, err := resolvePath("/home/user", wd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Absolute paths are joined to workDir, so /home/user becomes /home/user/home/user.
	want := "/home/user/home/user"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestNew_RejectsRoot(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic for root workDir, got none")
		}
	}()
	New("/", false)
}

func TestNew_RejectsEmpty(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic for empty workDir, got none")
		}
	}()
	New("", false)
}

func TestNew_NormalizesPath(t *testing.T) {
	e := New("/home/user", false)
	if e.workDir[len(e.workDir)-1] != '/' {
		t.Errorf("workDir must end with separator, got %q", e.workDir)
	}
	want := "/home/user/"
	if e.workDir != want {
		t.Errorf("got %q, want %q", e.workDir, want)
	}
}
