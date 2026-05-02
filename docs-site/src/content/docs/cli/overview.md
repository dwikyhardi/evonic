---
title: CLI Overview
description: Referensi lengkap perintah CLI Evonic.
---

CLI Evonic adalah main interface buat ngatur platform. Semua perintah bisa dijalanin lewat `./evonic <command>`.

## Cara Pemakaian

```bash
./evonic <command> [options]
```

## Daftar Perintah

| Perintah | Deskripsi |
|----------|-----------|
| `setup` | Wizard setup interaktif pertama kali |
| `start` | Mulai server Flask |
| `stop` | Stop server yang sedang jalan |
| `restart` | Restart server (stop → start daemon mode) |
| `status` | Cek status server |
| `reconfigure` | Reconfigure LLM provider, model, dll |
| `reconfigure --supervisor` | Reconfigure supervisor daemon |
| `doctor` | Diagnostik & health check sistem |
| `pass` | Set atau ganti password admin |
| `update` | Cek & apply self-update |
| `plugin` | Kelola plugin (list, install, uninstall, enable, disable, new) |
| `skill` | Kelola skill (list, add, get, rm) |
| `skillset` | Kelola skillset (list, get, apply) |
| `agent` | Kelola agent (list, get, add, enable, disable, remove) |
| `model` | Kelola model LLM (list, get, add, rm) |

## Fitur Baru

Beberapa fitur CLI yang baru aja ditambahin:

- **`evonic restart`** — Restart server langsung tanpa repot stop dulu
- **`evonic reconfigure --supervisor`** — Konfigurasi supervisor daemon secara interaktif
- **`evonic doctor`** — Sekarang ngecek juga supervisor config dan validasi Telegram settings

Klik link di sidebar buat detail masing-masing perintah!
