---
title: Mulai Cepat
description: Panduan cepat untuk memulai Evonic dari awal.
---

Selamat datang di Evonic! Halaman ini bakal ngejelasin langkah-langkah dasar buat mulai pakai Evonic.

## Prasyarat

- Python 3.9+
- Git
- Koneksi internet (buat download model LLM atau akses API provider)

## Instalasi

Clone repository dan masuk ke direktori project:

```bash
git clone https://github.com/anvie/evonic.git
cd evonic
```

## Setup Pertama

Jalankan wizard setup interaktif:

```bash
./evonic setup
```

Wizard ini akan memandumu untuk:

1. **Pilih LLM Provider** — Ollama, OpenAI, Anthropic, atau kustom.
2. **Set Base URL** — URL endpoint API provider.
3. **API Key** — Masukkan key kalau provider butuh autentikasi.
4. **Model** — Pilih model yang mau dipakai.
5. **Test Koneksi** — Wizard bakal ngetes koneksi ke provider.
6. **Gaya Komunikasi** — Pilih tone (professional, casual, dll).
7. **Password Admin** — Set password buat dashboard web.

## Menjalankan Server

### Start Server

```bash
./evonic start
```

Atau jalankan di background (daemon mode):

```bash
./evonic start --daemon
```

### Cek Status

```bash
./evonic status
```

### Stop Server

```bash
./evonic stop
```

### Restart Server

```bash
./evonic restart
```

Perintah `restart` ini adalah fitur baru yang ngestop server terus langsung start lagi dalam daemon mode. Praktis banget buat development!

## Selanjutnya

- Lihat [CLI Reference](/cli/overview/) buat daftar lengkap perintah CLI.
- Pelajari [evonic doctor](/cli/doctor/) buat ngecek kesehatan sistem.
- Atur [Supervisor](/cli/reconfigure/) biar Evonic bisa update otomatis.
