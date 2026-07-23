# Contributing to sonosify

Thanks for taking the time to contribute. This document covers everything you
need to set up a development environment, run the checks CI enforces, and get
a pull request merged.

## Requirements

- Python 3.13 or 3.14
- [uv](https://docs.astral.sh/uv/) for dependency management and running commands
- A Sonos speaker (or a few) on the same local network for manual/integration testing

## Getting set up

Clone the repository and install every dependency group, including the `cli`
extra and the `dev` group (pytest, ruff, pre-commit):

```powershell
uv sync --all-extras --dev
```

Install the pre-commit hooks so formatting/linting issues are caught before
they reach CI:

```powershell
uv run pre-commit install
```

## Running the test suite

```powershell
uv run pytest
```

Tests live under `tests/` and mirror the package layout in `sonosify/`. Prefer
unit tests that don't require real hardware; if a change needs verification
against an actual Sonos speaker, note that in the pull request description.

## Linting and formatting

The project uses [ruff](https://docs.astral.sh/ruff/) for both linting and
formatting, configured in `pyproject.toml`:

```powershell
uv run ruff check .
uv run ruff format .
```

`ruff format --check .` (without modifying files) is what CI runs, so run the
plain `ruff format .` locally first if it reports issues.

## Matching CI

CI (`.github/workflows/ci.yaml`) runs on Python 3.13 and 3.14 and executes, in
order: `ruff check`, `ruff format --check`, then `pytest`. Running the same
three commands locally before pushing will catch almost everything CI would
flag:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Project layout

- `sonosify/` — the core async library (discovery, client, events, models)
- `sonosify/cloud/` — OAuth2 and Sonos Control API client, models, and errors
- `sonosify/cli/` — the optional Typer-based CLI, one module per command group
  under `sonosify/cli/commands/`
- `examples/` — small runnable scripts demonstrating the core API
- `tests/` — the test suite

## Making changes

- Keep pull requests focused; unrelated refactors make review harder.
- Add or update tests for any behavior change.
- Update `README.md` if you add, rename, or remove a CLI command or a public
  API symbol — the CLI reference and the `sonosify.__init__` export list are
  expected to stay accurate.
- Conventional, descriptive commit messages (e.g. `fix(cli): ...`,
  `feat(client): ...`) are appreciated but not required.

## Reporting issues

Open an issue with as much detail as you can: Sonos model(s) involved, the
command or code path, expected vs. actual behavior, and — for CLI issues —
the output of the same command with `--debug` and `--format json`.
