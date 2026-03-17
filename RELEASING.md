# Release Guide

This document covers PyPI publishing setup and the ongoing release process.

Two publishing paths are supported — choose the one that works for your situation:

| Path | Setup effort | Security | Recommended |
|---|---|---|---|
| **A — OIDC Trusted Publisher** | One-time web UI config on pypi.org | No stored secrets | ✅ Yes |
| **B — API Token** | Create token + add GitHub secret | Token stored in GitHub | Fallback |

---

## Path A — OIDC Trusted Publisher (recommended)

### Step 1 — Register a Pending Trusted Publisher on pypi.org

Because `clawforge` doesn't exist on PyPI yet, use the **Pending Publisher** path.

Navigate to:

```
https://pypi.org/manage/account/publishing/
```

Click **"Add a new pending publisher"** and fill in **exactly**:

| Field | Value |
|---|---|
| PyPI Project Name | `clawforge` |
| Owner (GitHub username) | `hidearmoon` |
| Repository name | `openclaw-clawforge` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

Click **Save**.

> **Why these exact values?** A failed publish run confirmed the OIDC claims your
> workflow presents to PyPI:
> - `repository`: `hidearmoon/openclaw-clawforge`
> - `workflow_ref`: `.github/workflows/publish.yml`
> - `environment`: `pypi`
>
> The Trusted Publisher entry must match all three exactly (case-sensitive).

### Step 2 — Verify GitHub environment exists

The GitHub Actions environment `pypi` is already created. Confirm at:

```
https://github.com/hidearmoon/openclaw-clawforge/settings/environments
```

No extra reviewers or branch restrictions are needed for the initial release.

### Step 3 — Re-trigger the publish workflow

Since `v0.1.0` tag is already on the remote (from a failed first attempt),
use one of two options:

**Option 1 — manual dispatch** (no tag deletion needed):

```
https://github.com/hidearmoon/openclaw-clawforge/actions/workflows/publish.yml
```

Click **"Run workflow"**, type `publish` in the confirmation field, then run.

**Option 2 — delete and recreate the tag**:

```bash
git push origin :refs/tags/v0.1.0          # delete remote tag
git tag -d v0.1.0                           # delete local tag
git tag v0.1.0 -m "Release v0.1.0"         # recreate
git push origin v0.1.0                     # push → triggers publish.yml
```

### Step 4 — Verify on PyPI

Once the workflow completes (~2 min):

```
https://pypi.org/project/clawforge/
```

Then verify installation works:

```bash
pip install clawforge
clawforge --version
```

---

## Path B — API Token fallback

Use this when you can't complete the OIDC setup immediately and need to unblock publishing.

### Step 1 — Create a PyPI API token

1. Sign in to https://pypi.org and go to Account Settings → API tokens
2. Create a token scoped to **"Entire account"** (first upload) or **Project: clawforge** (subsequent)
3. Copy the token value (starts with `pypi-…`)

### Step 2 — Add the token as a GitHub secret

```
https://github.com/hidearmoon/openclaw-clawforge/settings/secrets/actions
```

Click **"New repository secret"**:

| Name | Value |
|---|---|
| `PYPI_TOKEN` | `pypi-…` (the token from step 1) |

### Step 3 — Re-trigger the publish workflow

Same as Path A Step 3 — use manual dispatch or delete and recreate the tag.

> When `PYPI_TOKEN` secret is set, `publish.yml` uses it automatically.
> When `PYPI_TOKEN` is absent/empty, the workflow falls back to OIDC.

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

### `invalid-publisher` — OIDC token exchange fails

```
Token request failed: valid token, but no corresponding publisher
(Publisher with matching claims was not found)
```

The Trusted Publisher on pypi.org doesn't match the workflow. Check:
- Workflow filename is **exactly** `publish.yml` (not `publish.yaml`)
- Environment name is **exactly** `pypi` (case-sensitive)
- Repository owner / name match `hidearmoon` / `openclaw-clawforge`

Fastest fix: switch to Path B (API token) while you sort out the OIDC setup.

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
