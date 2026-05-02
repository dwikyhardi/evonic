---
title: evonic doctor
description: Diagnostik sistem dan health check untuk Evonic.
---

Perintah `evonic doctor` adalah toolkit diagnostik buat ngecek kesehatan platform Evonic secara menyeluruh. Mulai dari environment, konfigurasi, koneksi, sampai layanan.

## Cara Pakai

```bash
./evonic doctor
```

Atau pake mode cepat (skip LLM provider test):

```bash
./evonic doctor --quick
```

## Yang Dicek

### 1. Environment Check 🌍

- **Python version** — minimal 3.9+
- **OS info** — sistem operasi dan arsitektur
- **Environment variables** — ngecek variabel penting kayak `PORT`, `HOST`, `SECRET_KEY`, `DEBUG`, dll
- **Dependencies** — ngecek ketersediaan Flask, requests, anthropic, sqlite3

### 2. Configuration Check ⚙️

- **`.env`** — ada atau nggak? isinya valid?
- **`config.py`** — properti penting kayak `BASE_DIR`, `DB_PATH`, `PORT`, `HOST`, `SECRET_KEY` udah terdefinisi?
- **Encoding** — `.env` readable dalam UTF-8?

### 3. Connection Check 🔌

- **Database** — koneksi SQLite berfungsi?
- **Redis** (opsional) — kalau dikonfigurasi, dicek juga
- **Internet** — koneksi ke httpbin.org buat mastiin internet jalan

### 4. Service Check 🏃

- **Server status** — apakah server lagi jalan?
- **Health endpoint** — bisa diakses? (kalo server jalan)
- **Port binding** — port yang dikonfigurasi udah terbind?

### 5. File/Folder Check 📁

Ngecek direktori penting ada dan writable:

| Direktori | Fungsi |
|-----------|--------|
| `logs/` | Log aplikasi |
| `data/` | Data persisten |
| `plugins/` | Direktori plugin |
| `skills/` | Direktori skill |
| `agents/` | Data agent |
| `skillsets/` | Template skillset |
| `templates/` | Template web |

### 6. Agent & Skill Health Check 🤖

- Jumlah agent (total, enabled, disabled)
- Super agent ada atau nggak
- Tools dan skills per agent
- Integritas manifest skill (`skill.json`) — dicek apakah valid JSON

### 7. LLM Provider Check 🧠

(Skip kalo pake `--quick`)

Tes koneksi ke setiap LLM model yang terdaftar:

- Hit `/models` endpoint
- Validasi response
- Timeout handling

### 8. Supervisor Config Check 🛡️ (Fitur Baru! 🔥)

Ini nih yang baru ditambahin — ngecek `supervisor/config.json` secara lengkap:

```bash
# Contoh output section Supervisor Config Check:
# 
# ── 8. Supervisor Config Check ──
#   supervisor/config.json found
#   ✔   app_root: /home/user/evonic
#   ✔   poll_interval: 300
#   ✔   health_port: 8080
#   ✔   health_temp_port: 8081
#   ✔   health_timeout: 5
#   ✔   monitor_duration: 30
#   ✔   keep_releases: 3
#   ✔   telegram_bot_token is configured
#   ✔   telegram_chat_id is configured
```

Yang divalidasi:

| Field | Validasi |
|-------|----------|
| `app_root` | Harus ada dan direktori beneran exist |
| `poll_interval` | Angka positif (min 1) |
| `health_port` | Angka positif dalam range port valid |
| `health_temp_port` | Angka positif |
| `health_timeout` | Angka positif |
| `monitor_duration` | Angka positif |
| `keep_releases` | Angka positif (min 1) |
| `telegram_bot_token` | Kalau kosong dikasih warning — suruh konfigurasi dari super agent channel |
| `telegram_chat_id` | Kalau kosong dikasih warning — suruh konfigurasi dari super agent channel |

Kalau file `supervisor/config.json` belum ada, doctor bakal ngasih tau bahwa self-update supervisor belum dikonfigurasi.

## Contoh Lengkap

```bash
$ ./evonic doctor

🧪  Evonic Doctor
  System diagnostics & health check

── 1. Environment Check ──
  ✔   Python 3.11.4
  OS: Linux 6.2.0 (x86_64)
  Port=8080
  ...

── 8. Supervisor Config Check ──
  supervisor/config.json found
  ✔   app_root: /home/user/evonic
  ⚠   telegram_bot_token is empty — configure it for supervisor notifications.
  ⚠   telegram_chat_id is empty — configure it for supervisor notifications.

── Summary ──
  Total checks: 24
  ✔ Passed:  21
  ⚠ Warnings: 3
  ✗ Failed:   0

  System is operational with minor warnings.
```

## Tips

- Jalankan `evonic doctor` rutin buat mastiin sistem sehat.
- Kalau ada **Failed** item, itu prioritas utama buat dibenerin.
- **Warning** nggak kritis, tapi better dibenerin — kayak ngisi Telegram token biar dapet notifikasi update.
- Pake `--quick` kalo lagi buru-buru dan cuma mau ngecek hal-hal dasar.
