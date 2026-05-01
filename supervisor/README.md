# Evonic Self-Update Supervisor

A stdlib-only update engine that keeps Evonic running the latest signed release.

---

## How it works

```
Git remote ──► git fetch --tags ──► git verify-tag ──► git worktree add
                                                              │
                                                    uv venv + uv pip install
                                                              │
                                                    health check on temp port
                                                              │
                                                    stop daemon ──► atomic swap ──► start daemon
                                                              │
                                                    monitor 60s ──► rollback on failure
```

Each release lives in `releases/<tag>/` with its own `.venv/`. Mutable data (DB, agents, logs) lives in `shared/` and is symlinked into each release.

---

## First-time setup

### 1. Migrate the flat repo to release-based layout

```bash
# Stop the server first
evonic stop

# Run migration (dry-run to preview)
python3 supervisor/migrate.py --dry-run

# Apply (creates releases/v0.1.0/, shared/, current symlink)
python3 supervisor/migrate.py --tag v0.1.0
```

### 2. Configure SSH tag signing

```bash
# Tell git to use SSH for signing
git config gpg.format ssh
git config user.signingkey ~/.ssh/id_ed25519  # or your key path

# Create allowed_signers file (maps email → public key)
echo "your@email.com $(cat ~/.ssh/id_ed25519.pub)" > shared/.ssh/allowed_signers

# Tell git where to find allowed signers
git config gpg.ssh.allowedSignersFile shared/.ssh/allowed_signers
```

### 3. Create and sign a release tag

```bash
# Sign the initial tag created by migrate.py
git tag -s -f v0.1.0 -m "Initial release"

# Verify it works
git verify-tag v0.1.0
# Expected output: Good "git" signature for ...

# For future releases:
git tag -s v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

### 4. Configure supervisor

Edit `supervisor/config.json` (created by migrate.py):

```json
{
    "app_root": "/path/to/evonic",
    "poll_interval": 300,
    "git_remote": "origin",
    "health_port": 8080,
    "health_temp_port": 18080,
    "health_timeout": 10,
    "monitor_duration": 60,
    "keep_releases": 3,
    "python_bin": "python3",
    "uv_bin": null,
    "telegram_bot_token": "123456:ABC-your-bot-token",
    "telegram_chat_id": "-100your_chat_id"
}
```

`uv_bin`: set to `"uv"` if uv is installed (much faster dep installs). Leave `null` to use `pip`.

### 5. Start the supervisor

```bash
# Foreground (for testing)
python3 supervisor/supervisor.py --config supervisor/config.json

# Background (production)
nohup python3 supervisor/supervisor.py --config supervisor/config.json \
    >> supervisor/run/supervisor.log 2>&1 &
```

On Linux with systemd, create `/etc/systemd/system/evonic-supervisor.service`:

```ini
[Unit]
Description=Evonic Update Supervisor
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/evonic
ExecStart=/usr/bin/python3 /path/to/evonic/supervisor/supervisor.py --config /path/to/evonic/supervisor/config.json
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable evonic-supervisor
sudo systemctl start evonic-supervisor
```

---

## CLI commands

```bash
# Check for available updates (no apply)
evonic update --check

# Trigger immediate update check on running supervisor
evonic update

# Update to a specific tag
evonic update --tag v1.3.0

# Roll back to previous release
evonic update --rollback

# Update without signature check (dev only)
evonic update --force
```

---

## Telegram notifications

The supervisor sends update progress to a Telegram chat. Set `telegram_bot_token` and `telegram_chat_id` in `config.json`.

**Progress** (edited in-place):
```
[Update v0.1.0 → v0.2.0]
████████░░░░░░░░ 50% — Installing dependencies
Started: 14:32:01
```

**Failure** (new message, stays visible):
```
❌ Update v0.2.0 FAILED at step 4/6
Rolled back to v0.1.0
Error: Staged release failed health check
```

**Success** (edits the progress message):
```
✅ Update to v0.2.0 complete
████████████████ 100% — Done
Started: 14:32:01
```

---

## Directory layout after migration

```
evonic/
├── .git/                    # single git object store
├── releases/
│   ├── v0.1.0/              # git worktree (previous)
│   │   └── .venv/
│   └── v0.2.0/              # git worktree (current)
│       ├── .venv/
│       ├── db -> ../../shared/db/      # symlink
│       ├── agents -> ../../shared/agents/
│       └── ...
├── current -> releases/v0.2.0/        # atomic symlink
├── rollback.slot            # "v0.1.0"
├── supervisor/
│   ├── supervisor.py
│   ├── migrate.py
│   ├── config.json          # gitignored
│   └── run/
│       ├── supervisor.pid
│       └── supervisor.log
└── shared/
    ├── db/evonic.db
    ├── agents/
    ├── logs/
    ├── run/evonic.pid
    ├── .env
    └── .ssh/allowed_signers
```

---

## Rollback semantics

If any update step fails, the supervisor automatically:
1. Swaps the `current` pointer back to `rollback.slot`
2. Restarts the daemon from the previous release
3. Removes the failed release worktree
4. Sends a Telegram failure alert

Manual rollback: `evonic update --rollback`

---

## Known limitations

- The supervisor is **not self-updating** — update it manually (it rarely changes)
- **No zero-downtime**: ~2-5s gap while old daemon stops and new one starts
- Windows symlinks require Developer Mode; junction fallback used for directories
- A compromised signing key cannot be detected — rotate keys immediately if suspected
