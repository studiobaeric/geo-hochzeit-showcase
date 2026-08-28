"""Regression tests for #43/#48: when packaged into a PyInstaller onefile
binary (see tools/build_release.py), `sys.frozen` is True and `__file__`
resolves inside PyInstaller's onefile temp extraction dir - which
PyInstaller wipes on exit - rather than next to the actual executable.
Every module that persists data to disk (game state, uploaded player
photos, round photos, the downloaded basemap) computes its own
PROJECT_ROOT with an `if getattr(sys, "frozen", False): ...` branch
specifically to avoid writing into that ephemeral directory.

Nothing previously exercised that branch: every other test in this suite
only ever imports these modules with `sys.frozen` unset, so only the
`else` (regular `python app.py`) path has ever run. Before this file, a
regression here (e.g. someone "simplifying" the branch away, or a typo in
`sys.executable` handling) could only be caught by actually building and
running the PyInstaller binary.

Each PROJECT_ROOT is computed once, at import time, as a module-level
constant - so the only way to exercise the frozen branch is to patch
sys.frozen/sys.executable and re-run that import-time computation via
importlib.reload(), not call some already-imported function differently.
"""

import importlib
import os
import sys

import pytest


@pytest.fixture
def fake_frozen_executable(tmp_path):
    """Simulates running as a PyInstaller onefile binary at
    <tmp_path>/dist/kartenquiz, the way tools/build_release.py's output is
    actually laid out (an executable with no source tree around it).

    Provides a `.reload(module)` helper that reloads a module under the
    faked sys.frozen/sys.executable. Whichever modules were reloaded this
    way are reloaded a *second* time - back to their normal, non-frozen
    state - only once this fixture has itself restored the real
    sys.frozen/sys.executable, so no other test in the suite is left with
    a module stuck pointing at this test's throwaway tmp_path.
    """
    fake_exe = tmp_path / "dist" / "kartenquiz"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.touch()

    had_frozen = hasattr(sys, "frozen")
    original_frozen = getattr(sys, "frozen", None)
    original_executable = sys.executable

    modules_to_restore = []

    class _Handle:
        path = fake_exe

        @staticmethod
        def reload(module):
            importlib.reload(module)
            modules_to_restore.append(module)
            return module

    sys.frozen = True
    sys.executable = str(fake_exe)
    try:
        yield _Handle
    finally:
        if had_frozen:
            sys.frozen = original_frozen
        else:
            del sys.frozen
        sys.executable = original_executable
        for module in modules_to_restore:
            importlib.reload(module)


def test_game_state_persists_next_to_frozen_executable(fake_frozen_executable):
    import game_state

    fake_frozen_executable.reload(game_state)

    expected_root = str(fake_frozen_executable.path.parent)
    assert game_state._PROJECT_ROOT == expected_root
    assert game_state.STATE_FILE == os.path.join(expected_root, "data", "game_state.json")


def test_photo_storage_persists_next_to_frozen_executable(fake_frozen_executable):
    import photo_storage

    fake_frozen_executable.reload(photo_storage)

    expected_root = str(fake_frozen_executable.path.parent)
    assert photo_storage.PROJECT_ROOT == expected_root
    assert photo_storage.PHOTOS_DIR == os.path.join(expected_root, "static", "photos")


def test_photo_config_persists_next_to_frozen_executable(fake_frozen_executable):
    import photo_config

    fake_frozen_executable.reload(photo_config)

    expected_root = str(fake_frozen_executable.path.parent)
    assert photo_config.PROJECT_ROOT == expected_root
    assert photo_config.PHOTOS_FILE == os.path.join(expected_root, "static", "config", "photos.json")


def test_map_build_persists_next_to_frozen_executable(fake_frozen_executable):
    import map_build

    fake_frozen_executable.reload(map_build)

    expected_root = str(fake_frozen_executable.path.parent)
    assert map_build.PROJECT_ROOT == expected_root
    assert map_build.MAP_CONFIG_FILE == os.path.join(expected_root, "data", "map_config.json")
    assert map_build.PHOTOS_FILE == os.path.join(expected_root, "static", "config", "photos.json")


def test_build_basemap_resolves_next_to_frozen_executable(fake_frozen_executable):
    from tools import build_basemap

    fake_frozen_executable.reload(build_basemap)

    assert build_basemap.PROJECT_ROOT == fake_frozen_executable.path.parent.resolve()
