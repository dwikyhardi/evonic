---
title: evonic reconfigure
description: Reconfigure LLM provider, supervisor, dan pengaturan Evonic lainnya.
---

Perintah `evonic reconfigure` adalah interactive wizard buat ngubah konfigurasi Evonic yang udah ada. Mulai dari ganti LLM provider sampai ngatur supervisor daemon.

## Reconfigure Platform

Tanpa flag, perintah ini bakal ngeganti konfigurasi platform secara lengkap:

```bash
./evonic reconfigure
```

Wizard ini bakal nanya:

1. **LLM Provider** — Ganti provider (Ollama, OpenAI, Anthropic, atau kustom).
2. **Base URL** — URL endpoint provider yang dipake.
3. **API Key** — API key kalo provider butuh autentikasi.
4. **Model Name** — Nama model yang dipake.
5. **Test Connection** — Ngetes koneksi ke provider.
6. **Communication Style** — Tone (professional, casual, friendly, dll).
7. **Language** — Bahasa yang dipake agent.
8. **Sandbox** — Aktif/nonaktifkan sandbox container.
9. **Password** — Ganti password admin dashboard.

## Reconfigure Supervisor (Fitur Baru! 🎯)

Ini dia yang baru! Flag `--supervisor` bakal ngejalanin wizard khusus buat ngatur supervisor daemon:

```bash
./evonic reconfigure --supervisor
```

### Yang Bisa Diatur

| Pengaturan | Default | Deskripsi |
|------------|---------|-----------|
| `poll_interval` | 300 detik | Seberapa sering supervisor ngecek release baru di GitHub |
| `health_port` | 8080 | Port buat health check server |
| `keep_releases` | 3 | Jumlah release lama yang disimpan (yang lebih lama otomatis diprun) |
| `telegram_bot_token` | — | Token bot Telegram buat notifikasi |
| `telegram_chat_id` | — | Chat ID Telegram tujuan notifikasi |

### Contoh Pemakaian

```bash
$ ./evonic reconfigure --supervisor

  Evonic Supervisor Reconfigure
  ==============================

  Configure the supervisor daemon that manages the server
  process, self-updates, and health checks.

  Poll interval — how often (in seconds) the supervisor checks
  for new releases on GitHub.

  Poll interval [300]: 60

  Health check port — the supervisor probes this port to
  determine whether the server is responsive after a swap.

  Health check port [8080]: 8081

  Release retention — how many past releases to keep
  (older ones are pruned after a successful update).

  Keep releases [3]: 5

  Telegram notifications — optionally notify a chat when
  the supervisor performs an update or encounters an error.

  Current bot token : (not set)
  Current chat ID   : (not set)

  Configure Telegram notifications? [y/N]: y
  Bot token [(not set)]: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
  Chat ID []: -1001234567890

  Supervisor Config Summary
  ──────────────────────────────
  Poll interval    : 60 seconds
  Health check port: 8081
  Keep releases    : 5
  Telegram token   : ***w11
  Telegram chat ID : -1001234567890

  Proceed? [Y/n]: y

  Supervisor config saved to supervisor/config.json
```

### Letak File Konfigurasi

Semua hasil konfigurasi supervisor disimpan di:

```
supervisor/config.json
```

### Validasi

Pas fitur `evonic doctor` jalan, konfigurasi supervisor juga bakal diperiksa:

- `app_root` — must exist dan valid
- `poll_interval`, `health_port`, dll — must angka positif
- `telegram_bot_token` — kalau kosong, dikasih warning
- `telegram_chat_id` — kalau kosong, dikasih warning

Cek [dokumentasi doctor](/cli/doctor/) buat detail lebih lanjut.
