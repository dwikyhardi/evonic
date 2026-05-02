---
title: Supervisor Daemon
description: Memahami supervisor daemon di Evonic — self-update, health checks, dan notifikasi.
---

Supervisor adalah komponen penting di Evonic yang ngejalanin server sebagai daemon dan ngatur **self-update**. Dia bertanggung jawab buat ngecek release baru, ngeswap versi, dan ngasih notifikasi.

## Cara Kerja Supervisor

```
┌─────────────┐     poll interval     ┌──────────────┐
│  Supervisor  │ ───────────────────▶ │  GitHub API   │
│  (daemon)    │ ◀─────────────────── │  (releases)   │
└──────┬──────┘     new release?      └──────────────┘
       │
       ▼
┌─────────────┐
│  Download    │
│  & Extract   │
└──────┬──────┘
       │
       ▼
┌─────────────┐     health check      ┌──────────────┐
│  Swap       │ ───────────────────▶ │  Health Port  │
│  Release    │ ◀─────────────────── │  (liveness)   │
└──────┬──────┘     response?        └──────────────┘
       │
       ▼
┌─────────────┐
│  Telegram   │
│  Notif      │
└─────────────┘
```

## Konfigurasi

Konfigurasi supervisor disimpan di `supervisor/config.json`. Kamu bisa ngatur lewat:

```bash
./evonic reconfigure --supervisor
```

### Field Konfigurasi

| Field | Tipe | Default | Deskripsi |
|-------|------|---------|-----------|
| `poll_interval` | int | 300 | Interval ngecek release (detik, min 60) |
| `health_port` | int | 8080 | Port buat health check server |
| `health_temp_port` | int | 8081 | Port sementara pas swap |
| `health_timeout` | int | 5 | Timeout health check (detik) |
| `monitor_duration` | int | 30 | Durasi monitoring post-swap (detik) |
| `keep_releases` | int | 3 | Jumlah release lama yang disimpan |
| `telegram_bot_token` | str | — | Token bot Telegram buat notifikasi |
| `telegram_chat_id` | str | — | Chat ID Telegram |

## Notifikasi Telegram

Supaya dapet notifikasi tiap kali supervisor update atau error, konfigurasiin Telegram:

1. Bikin bot lewat [@BotFather](https://t.me/BotFather) di Telegram.
2. Copy token bot-nya.
3. Cari tau chat ID kamu (bisa pake bot @userinfobot).
4. Jalanin:

```bash
./evonic reconfigure --supervisor
```

Terus isi token dan chat ID pas diminta.

## Cek Kesehatan

Jalanin `evonic doctor` buat ngecek validasi konfigurasi supervisor:

```bash
./evonic doctor
```

Bakal ngecek:
- ✅ `app_root` exist dan valid
- ✅ Semua numeric fields positif
- ✅ Token Telegram terisi (warning kalo kosong)
- ✅ Chat ID Telegram terisi (warning kalo kosong)
