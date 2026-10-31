<p align="center">
  <img src="assets/logo/thoth-logo.svg" alt="Thoth — AI short-form video strategist" width="520">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11--3.13-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/bun-React%2019-000000?style=flat-square&logo=bun&logoColor=white" alt="Bun">
</p>

<p align="center">
  🚧 <strong>Work in progress</strong> — under active development; APIs and behavior may change.
</p>

---

> *Named after **Thoth**, the ibis-headed Egyptian god — keeper of writing and wisdom, and the scribe of the gods. A tool that **writes, narrates, and spreads** stories.*

**Thoth** turns a viral post into a short-form video. A run acquires the source post (TikTok,
Instagram, X, YouTube, Threads), traces the original creator, gathers footage and materials,
and assembles a Content Set that opens in **Studio**, where the video is edited and rendered
with Remotion.

## Components

| Path | What it is |
|---|---|
| [`python/`](python/README.md) | The control plane: a FastAPI `/api/v1` and a Temporal worker that run every workflow (acquisition, attribution, footage, assembly) |
| [`dashboard/`](dashboard/) | The React 19 + TypeScript dashboard and Studio, built with Bun |
| [`renderer/`](renderer/), [`packages/`](packages/) | The Remotion render service and its composition packages |
| `compose.stage1.*.yml`, [`docker/`](docker/), [`deploy/`](deploy/) | The Stage 1 Docker stack, its offline smokes, and the Caddy `web` container |

The Rust engine and the TypeScript Scout layer were retired in October 2026; their history is
in [`CHANGELOG.md`](CHANGELOG.md).

## Running it

- **Stage 1 stack (Docker):** [docs/operations/stage1-local-docker.md](docs/operations/stage1-local-docker.md),
  deployed with `make deploy` from WSL. The dashboard is served at **http://localhost:8088**;
  people sign in with Google or GitHub and an emailed code.
- **Local development:** [docs/RUNNING.md](docs/RUNNING.md) — Temporal, FastAPI, the worker and
  the Vite dev server, plus the `thoth-control` client.
- **Dashboard hot reload:** run Vite with a personal developer token (`thoth-control tokens create`)
  and open http://localhost:5173:

  ```
  THOTH_DEV_TOKEN=thoth_pat_... bun --cwd=dashboard run dev
  ```

`make help` lists the task runner's targets: Python tests and lint, dashboard tests and build,
offline smokes, and the deploy.

## Documentation

| Document | What's in it |
|---|---|
| **[docs/python-control-plane.md](docs/python-control-plane.md)** | Topology, configuration, the v1 HTTP contract, events, sign-in and developer access, approvals, redaction, the soak |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Work not done yet, in order |
| **[docs/DESIGN.md](docs/DESIGN.md)** | Dashboard and Studio design reference |
| **[docs/adr/](docs/adr/)** · **[docs/decisions/](docs/decisions/)** | Architecture decisions |
| **[CHANGELOG.md](CHANGELOG.md)** · **[BLUEPRINT.md](BLUEPRINT.md)** | Change history · architecture and subsystem status |

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
