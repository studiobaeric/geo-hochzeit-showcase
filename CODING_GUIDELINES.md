# Coding Guidelines

We don't currently have a written set of coding guidelines beyond
`README.md` and `RELEASING.md`. This document collects a shared set of
conventions so contributions stay consistent as the codebase grows. It's a
living document — send corrections and additions as PRs.

## 1. General principles

- Prefer clarity over cleverness; optimize for the next reader, not fewer
  keystrokes.
- Keep changes minimal and focused — a bug fix shouldn't carry unrelated
  refactors.
- No dead code, commented-out blocks, or speculative abstractions for
  hypothetical future needs.
- Don't add error handling/validation for cases that can't occur; validate
  at real boundaries (user input, external APIs, file I/O).

## 2. Python (backend: `app.py`, `game_state.py`, `map_build.py`, `i18n.py`, `photo_config.py`, `photo_storage.py`, `tools/`)

- Target the Python version pinned in CI (`.github/workflows/tests.yml`,
  currently rolling `"3"` / newest stable CPython 3.x).
- Follow [PEP 8](https://peps.python.org/pep-0008/) for style; 4-space
  indentation.
- Use type hints on new/changed function signatures where practical.
- Docstrings: one line for simple functions; only add detail when
  behavior/invariants aren't obvious from the name and signature.
- Prefer `pathlib.Path` over raw string path manipulation for new code.
- Keep Flask route handlers thin — push logic into `game_state.py`/helper
  modules, keep `app.py` focused on routing/wiring.
- No secrets, API keys, or `.env` files committed (enforced by `gitleaks`
  in CI's `sanity-checks` job — see `.github/workflows/tests.yml`).

## 3. JavaScript / frontend (`static/`, `templates/`)

- Vanilla JS, no framework — keep it that way unless there's a strong
  reason to introduce one (discuss first).
- Use `const`/`let`, never `var`.
- Keep DOM manipulation and game/state logic separated where reasonable
  (mirrors the `static/config/` split already in use).
- CSS: one file per concern (see `static/css/*.css`) — keep new styles in
  the relevant file rather than growing `style.css` unboundedly.

## 4. Tests (`tests/`, pytest)

- New backend behavior should come with a corresponding `tests/test_*.py`
  (see existing files for naming conventions — API-route tests tend to use
  `test_<area>_api.py`, others just `test_<area>.py`).
- Run `pytest -v --cov --cov-report=term-missing` locally before pushing
  (matches CI).
- E2E/Playwright smoke tests live in `test_e2e_smoke.py` — only extend
  this for real user-flow coverage, not unit-level checks.
- Don't skip, disable, or weaken a test to make CI pass — fix the
  underlying issue.

## 5. Commits & PRs

- Commit messages: short imperative summary line, explain *why* in the
  body when not obvious.
- Keep PRs scoped to one topic; large unrelated changes should be split.
- CI must be green (pytest job, e2e-smoke, sanity-checks/gitleaks) before
  merge.

## 6. Internationalization

- User-facing strings go through `i18n.py` / the existing translation
  mechanism (see `tests/test_i18n_translations.py`) — no hardcoded UI
  strings bypassing it.

## 7. Documentation

- Update `README.md` for setup/usage-affecting changes.
- Update `RELEASING.md` for anything affecting the release/build process
  (`tools/build_basemap.py`, packaging).
- Update `CHANGELOG.md` for user-visible changes.
