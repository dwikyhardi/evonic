# Evonic Documentation Site

Documentation site for the [Evonic](https://github.com/anvie/evonic) platform — built with **Astro v5 + Starlight**.

## Prerequisites

- **Node.js** 18+
- **npm** (or bun, pnpm, yarn)

## Quick Start

```bash
npm install
npm run dev
```

Then open `http://localhost:4321` in your browser.

## Build

```bash
npm run build
```

Output ada di `dist/` — bisa langsung di-deploy ke static hosting.

## Project Structure

```
src/content/docs/
├── index.md              # Home page
├── getting-started.md    # Panduan mulai cepat
├── cli/
│   ├── overview.md       # Overview perintah CLI
│   ├── restart.md        # evonic restart (task #8)
│   ├── reconfigure.md    # evonic reconfigure --supervisor (task #9)
│   ├── doctor.md         # evonic doctor (task #10)
│   └── reference.md      # CLI reference lengkap
└── guide/
    └── supervisor.md     # Panduan supervisor daemon
```

## Tech Stack

- [Astro v5](https://astro.build)
- [Starlight](https://starlight.astro.build)
- Markdown / MDX
