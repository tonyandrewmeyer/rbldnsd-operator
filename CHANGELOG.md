# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Renamed the charm from `rbldnsd-test` to `rbldnsd` in `charmcraft.yaml`.
- Switched the charm to depend on PyPI `charmlibs-apt` and `charmlibs-systemd`
  instead of fetching `operator_libs_linux` from Charmhub. The committed
  `lib/` directory has been removed.
- Bumped the `ops` dependency to `~=3.7`, dropped the hard requirement on
  Python 3.11 (now `>=3.10`), and adopted PEP 735 `[dependency-groups]` for
  development dependencies.
- Reworked `tox.ini` to use `tox-uv` and the `uv-venv-lock-runner`, with
  dependencies sourced from the lock file via `dependency_groups`.
- Switched integration tests to use a `charm` fixture in `conftest.py` (rather
  than packing inside test bodies) and pinned `jubilant>=1.8,<2` and
  `pytest-jubilant>=2,<3` to match the current best practice.
- Tightened CI: matrix over Python 3.10 / 3.12 / 3.14; integration tests now use
  Concierge to set up a machine model and run on every PR.
- Refreshed `pre-commit` hooks (newer pre-commit-hooks and ruff revisions), and
  changed the local `ty` and `pytest` hooks to run via `uv run --frozen` so they
  use the versions pinned in `uv.lock`.
- Updated `SECURITY.md` to remove a stale reference to another project.

## [1.0.0a1] - 2025-07-17

- Initial alpha version.
