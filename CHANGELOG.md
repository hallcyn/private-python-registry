# Changelog

All notable changes to this template are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-11

### Added
- Initial release of the `private-python-registry` Railway template.
- `Dockerfile` based on `python:3.12-slim` with `devpi-server`, `devpi-web`, and `devpi-client`.
- Idempotent `entrypoint.sh`: generates a persistent `--secretfile`, runs `devpi-init` once, bootstraps the root password from `DEVPI_ROOT_PASSWORD` on first init, then `exec`s `devpi-server` on `0.0.0.0:$PORT`.
- `railway.json` with Dockerfile builder, `/+api` healthcheck, and failure restart policy.
- End-to-end smoke test (`scripts/smoke-test.sh`) covering build → user/index creation → `devpi upload` → `pip install` → restart-on-same-volume persistence check.
- GitHub Actions CI running the smoke test on every push/PR to `main`.
- User-facing README with deployment steps, usage examples for `pip`/`uv`/`twine`, environment variables, volume layout, limitations, and troubleshooting.
