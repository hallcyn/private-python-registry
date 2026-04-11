# Private Python Registry

**Deploy your own private PyPI-compatible package registry on Railway in under 2 minutes.**
Based on [devpi](https://devpi.net), with persistent storage and full compatibility with `pip`, `uv`, and `twine`.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/4_qIAt?referralCode=0fPTYP&utm_medium=integration&utm_source=template&utm_campaign=generic)

---

## What you get

- A private Python package index served by `devpi-server` + `devpi-web` (web UI + search).
- Standard tooling: publish with `twine` or `devpi upload`, install with `pip` or `uv`.
- On-demand PyPI mirror: any package fetched through your index is cached in your volume.
- Persistent storage on a Railway volume — redeploys don't wipe your packages or logins.
- One service, one container, one volume. No Postgres, no reverse proxy, no moving parts.

## Prerequisites

- A [Railway](https://railway.com) account.
- Local `pip` / `uv` / `twine` / `devpi-client` for publishing and installing.

## Deploy

1. **Deploy the template** on Railway (button above, or `railway init` from a fork of this repo).
2. **Attach a Volume** to the service and mount it at `/data`. This is mandatory — without it, your packages and logins are lost on every redeploy.
3. **Set `DEVPI_ROOT_PASSWORD`** in the service variables *before the first deploy*. This seeds the devpi `root` account. If you skip it, `root` starts with an empty password and you'll have to change it manually via `devpi-client`.
4. **Generate a public domain** in the Railway service settings (Networking → Generate Domain). Railway does not assign one automatically.
5. Wait for the health check on `/+api` to go green. You're live at `https://<your-domain>/`.

## Use it

### Configure the devpi client

```bash
pip install devpi-client
devpi use https://<your-domain>
devpi login root --password="$DEVPI_ROOT_PASSWORD"
```

### Create a user and a private index

```bash
devpi user -c alice password=s3cret email=alice@example.com
devpi login alice --password=s3cret
devpi index -c prod bases=root/pypi
devpi use alice/prod
```

`bases=root/pypi` makes your index fall through to the on-demand PyPI mirror, so `pip install`ing a public dependency through your index Just Works.

### Publish a package

With `devpi upload` (builds + uploads from the current project):

```bash
devpi upload --formats sdist,bdist_wheel
```

With `twine` (from an existing `dist/`):

```bash
twine upload \
  --repository-url https://<your-domain>/alice/prod/ \
  --username alice --password s3cret \
  dist/*
```

### Install from your private index

With `pip`:

```bash
pip install \
  --index-url https://alice:s3cret@<your-domain>/alice/prod/+simple/ \
  my-private-pkg
```

With `uv`:

```bash
uv pip install \
  --index https://alice:s3cret@<your-domain>/alice/prod/+simple/ \
  my-private-pkg
```

For CI, prefer a scoped token over a password: see [`devpi-tokens`](https://pypi.org/project/devpi-tokens/).

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `3141` | Set by Railway. The server binds `0.0.0.0:$PORT`. |
| `DEVPI_ROOT_PASSWORD` | *(unset)* | One-shot bootstrap of the `root` password on **first** init. Changing it later has no effect — use `devpi user -m root password=...`. |
| `DEVPI_SERVERDIR` | `/data/server` | Where devpi stores packages, indexes, and metadata. Must be on the mounted volume. |
| `DEVPI_SECRETFILE` | `/data/.secret` | Persistent server secret. Required so login tokens survive a redeploy. |
| `DEVPI_RESTRICT_MODIFY` | `root` | Only `root` can create users/indexes. Set to an empty string to allow any logged-in user to create their own. |

## Persistence & the `/data` volume

Everything stateful lives under `/data`:

```
/data/
├── server/          # devpi serverdir: packages, indexes, users
├── .secret          # generated on first boot, keeps login tokens valid across redeploys
└── .initialized     # sentinel so devpi-init runs exactly once
```

If you ever want a clean slate, delete the volume (or wipe `.initialized`) and redeploy.

## v1 limitations

- **SQLite-backed** (devpi default). Fine for small-to-medium teams. Postgres backend is not configured.
- **No reverse proxy**, no `devpi-lockdown`. Anonymous reads of public indexes are allowed by devpi's default ACLs.
- **Single replica** — no HA.
- Credentials in install URLs are visible in shell history. Use `devpi-tokens` for CI.

These are intentional trade-offs to keep the template simple and reliable. Fork it if you need more.

## Troubleshooting

**"I get a 404 at my domain."** You forgot to Generate Domain in the Railway UI, or the health check on `/+api` hasn't gone green yet.

**"My login tokens keep getting invalidated after a redeploy."** The secret file isn't persisted — check that your volume is actually mounted at `/data` and that `/data/.secret` survives a restart.

**"`devpi upload` says permission denied."** You're using the wrong index. Run `devpi use <user>/<index>` and `devpi login <user>` before uploading.

**"`pip install` can't find my private package."** Double-check you're hitting `/<user>/<index>/+simple/` (the `+simple` suffix is mandatory for PEP 503).

**"Redeploy wiped my packages."** No volume attached, or it's mounted somewhere other than `/data`. Re-check the service settings.

## Local development

```bash
./scripts/smoke-test.sh
```

Builds the image, boots a throwaway container, exercises the full user/index/upload/install flow, then restarts the container on the same volume to verify persistence.

## License

MIT. See [LICENSE](./LICENSE).
