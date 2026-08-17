# Releasing

This project ships downloadable Windows/macOS/Linux binaries as GitHub
Releases, built and published automatically by
[`.github/workflows/release.yml`](.github/workflows/release.yml). Cutting a
release is a two-step split between a human and CI:

1. **A human marks a version** by moving the changelog entries and pushing a
   tag.
2. **CI does everything else**: it re-runs the full test suite
   ([`tests.yml`](.github/workflows/tests.yml): pytest, the Playwright
   end-to-end smoke test, and the gitleaks/`.env` sanity checks), and only if
   that passes does it build a binary for each OS
   ([`tools/build_release.py`](tools/build_release.py)) and publish them as
   assets on a new GitHub Release. If any test fails, the build and release
   jobs never run and nothing is published.

Versioning follows [Semantic Versioning](https://semver.org/)
(`vMAJOR.MINOR.PATCH`):

- **MAJOR** - incompatible changes to the game state API or save format.
- **MINOR** - new features, backwards compatible.
- **PATCH** - bug fixes, no behavior/API change.

## Cutting a release

1. Make sure `master` is green (check the
   [Tests workflow](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/tests.yml)).
2. Update [`CHANGELOG.md`](CHANGELOG.md): rename `## [Unreleased]` to the new
   version and date, e.g. `## [1.2.0] - 2026-08-12`, and add a fresh empty
   `## [Unreleased]` section above it. Commit this on `master`
   (e.g. `git commit -m "Release v1.2.0"`).
3. Tag that commit and push the tag:

   ```bash
   git tag v1.2.0
   git push origin v1.2.0
   ```

4. Watch the
   [Release workflow run](https://github.com/n1c01/Geo_Hochzeit/actions/workflows/release.yml)
   it triggers. Once it finishes, `v1.2.0` appears under
   [Releases](https://github.com/n1c01/Geo_Hochzeit/releases) with three
   attached archives (`kartenquiz-linux.tar.gz`,
   `kartenquiz-macos.tar.gz`, `kartenquiz-windows.zip`)
   plus auto-generated release notes (commits since the previous tag).

If the workflow fails partway (e.g. a flaky build), fix the problem, delete
the tag both locally and on GitHub (`git tag -d v1.2.0 && git push origin
:refs/tags/v1.2.0`; also delete the draft/partial release if one was
created), and start again from step 3 once the fix is on `master`.

## What's inside a release archive

Each archive is produced by [`tools/build_release.py`](tools/build_release.py)
and unpacks to a single folder containing:

- the platform executable (`kartenquiz` / `.exe`), built with
  [PyInstaller](https://pyinstaller.org/);
- `templates/` and `static/` (everything checked into git under those
  paths - UI, config, checked-in wedding photos, etc.);
- an empty `data/` folder for the game's persisted state;
- a `VERSION` file (the tag) that the app serves at `/api/version`;
- a `README.txt` with first-run instructions.

**Not included:** the offline map (`static/data/basemap.pmtiles`) and glyph
fonts (`static/fonts/`). Both are large, environment-specific, and already
gitignored/built locally via `tools/build_basemap.*` and
`tools/fetch_fonts.*` (see the main [README](README.md)) - baking them into
every CI build would make releases huge and slow to build. Users who want
the offline map run those scripts once and copy the results into the
unpacked release folder.

## Trying a build locally before tagging

```bash
pip install -r requirements-build.txt
python tools/build_release.py --version dev
```

This produces the same archive CI would, under `dist/`, using whatever OS
you run it on.
