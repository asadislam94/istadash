# IstaDash

> [!NOTE]
> This project was built through AI-assisted vibe coding!

Local energy dashboard for syncing heat meter readings from the [My ista UK portal](https://myista.co.uk) to your machine, with a clean visual dashboard — all in a self-contained native desktop window.

- **No cloud, no subscription.** Data is stored locally in SQLite.
- **Secure by design.** Your session token lives in the OS credential vault (Keychain / Credential Manager / Secret Service). No plain-text secrets anywhere.
- **Cross-platform.** Runs on Linux, macOS, and Windows.

---

## What it does

- One-time login flow inside the app — no config files to edit manually.
- Fetches paginated meter readings from the ista portal and stores them locally with deduplication.
- Dashboard with:
  - Usage graph (daily / weekly / monthly aggregation via Plotly)
  - Readings table with pagination
  - Sync history
  - CSV / JSON export with optional date filters
- Manual or automatic background refresh from the dashboard.

---

## Requirements

| OS | Supported |
|---|---|
| Linux | Ubuntu 22.04+, Debian 12+, or equivalent |
| macOS | 13 (Ventura) or later |
| Windows | 10 or later |

No Python installation required for end users — the Briefcase-built installer bundles everything.

---

## Installation

Download the pre-built installer for your platform from the [latest GitHub Release](https://github.com/asadislam94/istadash/releases/latest):

| Platform | File to download |
|---|---|
| Linux | `IstaDash-<version>-x86_64.AppImage` |
| macOS | `IstaDash-<version>.dmg` |
| Windows | `IstaDash-<version>.msi` |

### Linux

```bash
chmod +x IstaDash-*.AppImage
./IstaDash-*.AppImage
```

### macOS

Open the `.dmg`, drag IstaDash to Applications, and launch it.

### Windows

Double-click the `.msi` to install, then launch IstaDash from the Start menu.

> The AppImage bundles Python and all Python dependencies. No `pip install` or `apt install` is needed.

---

## First run

Launch IstaDash using the installer you just ran. A window opens. Follow the three-step setup inside the app:

1. **Sign in** — enter your My ista portal email and password.
2. **Select property** — choose your property from the list.
3. **Select meter** — choose your heat meter.

IstaDash stores only your session token in the OS credential vault and persists your meter selection to `~/.config/istadash/config.json`. An initial data sync runs automatically.

From then on, launch IstaDash the same way you did the first time.

---

## Running without the desktop window (browser mode)

If you prefer to use your own browser:

```bash
python -m istadash.main
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## Data locations

| Purpose | Path |
|---|---|
| Config (meter / property selection) | `~/.config/istadash/config.json` |
| SQLite database | `~/.local/share/istadash/meter_reads.db` |
| CSV / JSON exports | `~/.local/share/istadash/exports/` |

---

## Development setup

### Prerequisites

- Python 3.11 or 3.12
- [VS Code](https://code.visualstudio.com/) (recommended — full config included)
- **Linux only:** Qt WebEngine system libraries (required for the desktop window to work when running from source):
  ```bash
  sudo apt install \
    libnspr4 libnss3 libgbm1 libxcomposite1 \
    libxkbcommon0 libxkbcommon-x11-0 libxrandr2 \
    libasound2t64 libxkbfile1 python3-dev \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
    libxcb-shape0 libxcb-xkb1
  ```
  > These are only needed when running directly from source (i.e. `python -m istadash`). The packaged AppImage bundles everything.

### 1 — Clone and create the virtual environment

```bash
git clone https://github.com/asadislam94/istadash.git
cd istadash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
```

### 2 — Install with dev extras

```bash
pip install -e ".[dev]"
```

This installs the app in editable mode plus `pytest`, `ruff`, and `briefcase`.

### 3 — Open in VS Code

```bash
code .
```

VS Code will prompt you to install the recommended extensions (Python, Ruff, Jinja, TOML). Accept them all.

**The interpreter is pre-configured** to `.venv/bin/python` — no manual interpreter selection needed.

### VS Code tasks (Ctrl+Shift+B for default build, Ctrl+Shift+P → "Run Task" for all)

| Task | What it does |
|---|---|
| **Briefcase: package (Linux)** *(default build)* | Full create → build → package pipeline |
| **Briefcase: create (Linux)** | Scaffold the Linux app bundle |
| **Briefcase: build (Linux)** | Build the bundle (auto-creates first) |
| **Briefcase: update (Linux)** | Sync source changes into an existing bundle |
| **Briefcase: dev** | Run the packaged app in Briefcase dev mode |
| **Test** *(default test)* | Run pytest |
| **Lint** | Run ruff check |
| **Lint: fix** | Run ruff check --fix |

### VS Code launch configs (F5 / Run & Debug panel)

| Config | What it does |
|---|---|
| **IstaDash: Desktop window (PyWebView)** | Opens the native desktop window with debugger attached |
| **IstaDash: Flask (dev server)** | Starts Flask with `FLASK_DEBUG=1`; open browser at `http://127.0.0.1:8000` |
| **IstaDash: pytest** | Runs tests with debugger attached |

### Running tests manually

```bash
.venv/bin/python -m pytest --tb=short -v
```

### Linting manually

```bash
.venv/bin/ruff check istadash tests        # check
.venv/bin/ruff check istadash tests --fix  # auto-fix
```

---

## Building installers

Installers are produced with [Briefcase](https://briefcase.readthedocs.io/).

### Linux

```bash
.venv/bin/briefcase create linux
.venv/bin/briefcase build linux
.venv/bin/briefcase package linux
```

Output: `dist/` directory containing an AppImage or system package.

### macOS

```bash
briefcase create macos
briefcase build macos
briefcase package macos
```

### Windows

```powershell
briefcase create windows
briefcase build windows
briefcase package windows
```

> Cross-compilation is not supported. Build each platform on its corresponding OS (or use the GitHub Actions release workflow — see `.github/workflows/release.yml`).

---

## CI / CD

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push and pull request | Lint (ruff) + tests (pytest) on ubuntu-latest |
| `release.yml` | Push a `v*.*.*` tag | Builds installers on Linux, macOS, and Windows; creates a GitHub Release |

To publish a new release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

---

## Project structure

```
istadash/
├── istadash/               # Main package
│   ├── __main__.py         # Desktop entry point (PyWebView)
│   ├── main.py             # Flask app + all routes
│   ├── config.py           # Settings dataclass (reads ~/.config/istadash/)
│   ├── storage.py          # SQLite layer (readings, sync runs)
│   ├── security.py         # OS keyring helpers
│   ├── ista_client.py      # ista portal HTTP client
│   ├── services/
│   │   └── sync.py         # Sync orchestration
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS
├── tests/                  # pytest test suite
├── .github/workflows/      # CI and release workflows
├── .vscode/                # VS Code tasks, launch, settings, extensions
├── pyproject.toml          # Project metadata, deps, pytest, ruff, briefcase
└── LICENSE                 # MIT
```

---

## Secure storage model

- Session token is stored in the **OS credential vault** (macOS Keychain, Windows Credential Manager, Linux Secret Service / libsecret).
- No passwords or tokens are ever written to disk in plain text.
- If the session expires, the app redirects to the login screen automatically.

---

## Troubleshooting

**"No module named 'gi'" warning on Linux**
Harmless. PyWebView tries GTK first, then falls back to Qt. The Qt backend is what's used.

**Dashboard window doesn't open on Linux**
Make sure all system libraries listed in [Linux system libraries](#linux-system-libraries) are installed.

**"Login failed" on first run**
Double-check your My ista portal credentials at [myista.co.uk](https://myista.co.uk).

**Session expired / redirected to login**
Click "Refresh" — if your session has expired it will prompt you to log in again.

**Port 8000 already in use**
Change `flask_port` in `~/.config/istadash/config.json`, or kill the existing process:
```bash
fuser -k 8000/tcp
```
