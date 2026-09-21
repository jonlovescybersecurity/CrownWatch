# CrownWatch V1.1 — Git-Ready Update Build

This is intended to be the last CrownWatch ZIP required for normal development updates.

## New project layout

```text
CrownWatch/
├── app.py
├── static/
├── data/
│   └── crownwatch.db      # local only, ignored by Git
├── .gitignore
├── connect-github.ps1
├── update-and-run.ps1
├── run.ps1
├── migrate-history.ps1
└── setup-api-key.ps1
```

## 1. Preserve your current history

Run:

```powershell
.\migrate-history.ps1
```

Paste the full path to the `crownwatch.db` file from your current CrownWatch installation.

The database is copied to `data\crownwatch.db`, which Git ignores.

## 2. Create one empty GitHub repository

On GitHub create a repository named `CrownWatch` (or another name you prefer).

For the easiest setup, leave all initialization options unchecked:
- no README
- no .gitignore
- no license

Copy the repository HTTPS URL.

## 3. Connect this folder once

```powershell
.\connect-github.ps1
```

Paste the repository HTTPS URL when prompted. The script initializes Git, commits CrownWatch, adds `origin`, and pushes `main`.

## 4. Future workflow

From then on, use:

```powershell
.\update-and-run.ps1
```

That runs a safe fast-forward-only `git pull` and starts CrownWatch.

## Persistent data

Git does not track:
- `data/crownwatch.db`
- SQLite WAL/SHM files
- `.env`
- Python cache files

So pulling a new CrownWatch version does not overwrite your live history database.

Your Supercell API key remains in your Windows user environment variable if you previously used `setup-api-key.ps1`.
