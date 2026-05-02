---
title: CLI Reference Lengkap
description: Daftar lengkap semua perintah CLI Evonic dengan opsi-opsinya.
---

Halaman ini berisi referensi lengkap semua perintah CLI Evonic. Cocok buat kamu yang suka cari informasi cepet.

## `evonic setup`

Wizard interaktif buat setup pertama kali Evonic.

```bash
./evonic setup
```

## `evonic start`

Mulai server Flask.

```bash
./evonic start [options]
```

| Opsi | Default | Deskripsi |
|------|---------|-----------|
| `--port PORT` | dari config / 8080 | Port buat server |
| `--host HOST` | dari config / 0.0.0.0 | Host binding |
| `--debug` | — | Mode debug |
| `-d, --daemon` | `false` | Jalanin di background |

## `evonic stop`

Stop server yang lagi jalan.

```bash
./evonic stop
```

## `evonic restart`

Restart server (stop → start daemon). [Detail selengkapnya](/cli/restart/).

```bash
./evonic restart
```

## `evonic status`

Cek apakah server jalan atau nggak.

```bash
./evonic status
```

## `evonic reconfigure`

Wizard interaktif buat ngubah konfigurasi yang udah ada. [Detail selengkapnya](/cli/reconfigure/).

```bash
./evonic reconfigure [options]
```

| Opsi | Deskripsi |
|------|-----------|
| `--supervisor` | Reconfigure supervisor daemon (poll interval, port, Telegram, dll) |

## `evonic doctor`

Diagnostik sistem lengkap. [Detail selengkapnya](/cli/doctor/).

```bash
./evonic doctor [options]
```

| Opsi | Deskripsi |
|------|-----------|
| `--quick` | Skip tes LLM provider (lebih cepet) |

## `evonic pass`

Set atau ganti password admin dashboard.

```bash
./evonic pass
```

## `evonic update`

Cek dan apply update Evonic.

```bash
./evonic update [options]
```

| Opsi | Deskripsi |
|------|-----------|
| `--check` | Cek update aja, jangan apply |
| `--force` | Skip verifikasi signature (development only) |
| `--tag TAG` | Update ke tag tertentu |
| `--rollback` | Kembali ke release sebelumnya |

## `evonic plugin`

Kelola plugin.

```bash
./evonic plugin <subcommand> [args]
```

| Subcommand | Argumen | Deskripsi |
|------------|---------|-----------|
| `list` | — | Lihat daftar plugin |
| `install` | `<path>` | Install plugin dari zip/directory |
| `uninstall` | `<plugin-id>` | Uninstall plugin |
| `enable` | `<plugin-id>` | Aktifkan plugin |
| `disable` | `<plugin-id>` | Nonaktifkan plugin |
| `new` | — | Scaffold plugin baru |

## `evonic skill`

Kelola skill.

```bash
./evonic skill <subcommand> [args]
```

| Subcommand | Deskripsi |
|------------|-----------|
| `list` | Lihat daftar skill |
| `add` | Tambah skill baru |
| `get` | Lihat detail skill |
| `rm` | Hapus skill |

## `evonic skillset`

Kelola skillset.

```bash
./evonic skillset <subcommand> [args]
```

| Subcommand | Deskripsi |
|------------|-----------|
| `list` | Lihat daftar skillset |
| `get` | Lihat detail skillset |
| `apply` | Apply skillset ke agent |

## `evonic agent`

Kelola agent.

```bash
./evonic agent <subcommand> [args]
```

| Subcommand | Deskripsi |
|------------|-----------|
| `list` | Lihat daftar agent |
| `get` | Lihat detail agent |
| `add` | Tambah agent baru |
| `enable` | Aktifkan agent |
| `disable` | Nonaktifkan agent |
| `remove` | Hapus agent |

## `evonic model`

Kelola model LLM.

```bash
./evonic model <subcommand> [args]
```

| Subcommand | Deskripsi |
|------------|-----------|
| `list` | Lihat daftar model |
| `get` | Lihat detail model |
| `add` | Tambah model baru |
| `rm` | Hapus model |
