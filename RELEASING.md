# Release Guide

This document covers the one-time PyPI Trusted Publisher setup and the ongoing release process.

---

## One-Time Setup: PyPI Trusted Publisher (OIDC)

The `publish.yml` workflow uses GitHub OIDC — no API tokens stored as secrets. Before the **first ever** tag push, the PyPI side must be configured.

### Step 1 — Create a PyPI account / log in

Go to <https://pypi.org> and sign in.

### Step 2 — Register a Pending Trusted Publisher

Because `clawforge` doesn't exist on PyPI yet, use the **"Pending Publisher"** path (registers the publisher before the package is first uploaded).

Navigate to:

```
https://pypi.org/manage/account/publishing/
```

Click **"Add a new pending publisher"** and fill in:

| Field | Value |
|---|---|
| PyPI Project Name | `clawforge` |
| Owner (GitHub username / org) | `hidearmoon` |
| Repository name | `openclaw-clawforge` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

Click **Save**.

### Step 3 — Verify GitHub environment exists

The GitHub Actions environment `pypi` was already created programmatically. Confirm at:

```
https://github.com/hidearmoon/openclaw-clawforge/settings/environments
```

No reviewers or branch restrictions are required for the initial release. Add required reviewers later for stricter control.

### Step 4 — Trigger the first release

```bash
git tag v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Watch the Actions run at:

```
https://github.com/hidearmoon/openclaw-clawforge/actions
```

The pipeline is: **test → build → publish**. All three must go green.

### Step 5 — Verify on PyPI

Once the workflow completes:

```
https://pypi.org/project/clawforge/
```

Then verify installation works:

```bash
pip install clawforge
clawforge --version
```

---

## Ongoing Releases

For every subsequent release:

1. Update `version` in `pyproject.toml`
2. Commit: `git commit -am "chore: bump version to vX.Y.Z"`
3. Tag and push:
   ```bash
   git tag vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```
4. The `publish.yml` workflow runs automatically.

---

## Troubleshooting

### OIDC token exchange fails (`403 Forbidden` from PyPI)

The Trusted Publisher on pypi.org doesn't match the workflow. Double-check:
- Workflow filename is exactly `publish.yml` (not `publish.yaml`)
- Environment name is exactly `pypi` (case-sensitive)
- Repository owner / name are correct

### Build fails

Run locally to reproduce:

```bash
pip install build
python -m build
```

### Tests fail in CI

Run locally:

```bash
pip install -e ".[dev]"
pytest --tb=short -q
```
