---
title: evonic restart
description: Restart server Evonic dengan satu perintah.
---

Perintah `evonic restart` ngestop server yang sedang jalan, lalu langsung menyalakannya lagi dalam mode daemon. Gausah repot ngetik `stop` terus `start` manual!

## Cara Pakai

```bash
./evonic restart
```

## Cara Kerja

Di belakang layar, perintah ini ngelakuin dua hal secara berurutan:

1. **Stop server** — matiin proses server yang lagi jalan (kalau ada).
2. **Start server** — jalanin ulang server di background (daemon mode).

Ada jeda 1 detik di antara stop dan start buat mastiin port udah released.

## Contoh

```bash
# Restart server
$ ./evonic restart
Stopping server...
Starting server...
```

## Bedanya sama Manual Stop + Start?

Daripada kamu ngetik:

```bash
./evonic stop
./evonic start -d
```

...mending pake satu baris:

```bash
./evonic restart
```

Lebih cepet, lebih rapi. ✨

## Kapan Perlu Restart?

- Abis ganti konfigurasi environment
- Abis update plugin atau skill
- Server lemot atau error aneh-aneh
- Development cycle — ganti kode, restart, test

## Catatan

- Pastikan Evonic udah di-setup dulu (`./evonic setup`) sebelum pake restart.
- Restart otomatis pake daemon mode — jadi terminal kamu gak bakal ke-block.
