"""Guards against a regression that reached a real user: build_basemap.ps1
constructed a Windows pmtiles-CLI download URL that 404'd, because the
protomaps/go-pmtiles release asset naming isn't consistent across
platforms - macOS uses a hyphen ("go-pmtiles-VERSION_OS_ARCH.zip"), while
Windows uses an underscore ("go-pmtiles_VERSION_OS_ARCH.zip"), and Linux
uses an underscore with a .tar.gz extension.

Each build_basemap* script hardcodes its own URL template for its own
platform, so there's no shared code path to unit test - this instead
re-derives the exact URL each script would request for its pinned
PMTILES_VERSION and confirms the asset actually exists in the real
protomaps/go-pmtiles release. If a future go-pmtiles release changes
naming again, this fails loudly here instead of on someone's machine.

Needs network access (a HEAD request to github.com); skips gracefully if
that isn't available rather than failing the suite over connectivity.
"""

import os
import re
import urllib.error
import urllib.request

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(script_name):
    with open(os.path.join(PROJECT_ROOT, "tools", script_name)) as f:
        return f.read()


# Each script spells its default differently (bash parameter expansion vs.
# PowerShell's if/else), so match each syntax explicitly rather than one
# generic pattern that could silently match the wrong thing (or nothing).
_VERSION_PATTERNS = [
    r'PMTILES_VERSION:-(\d+\.\d+\.\d+)',  # bash: ${PMTILES_VERSION:-1.30.3}
    r'else\s*\{\s*"(\d+\.\d+\.\d+)"\s*\}',  # PowerShell: else { "1.30.3" }
]


def _pinned_version(script_text):
    for pattern in _VERSION_PATTERNS:
        match = re.search(pattern, script_text)
        if match:
            return match.group(1)
    raise AssertionError("could not find a pinned PMTILES_VERSION in the script")


def _asset_exists(url):
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except (urllib.error.URLError, TimeoutError) as e:
        pytest.skip(f"no network access to verify release asset ({e})")


RELEASE_URL_CASES = [
    pytest.param(
        "build_basemap_linux.sh",
        lambda version: (
            "https://github.com/protomaps/go-pmtiles/releases/download/"
            f"v{version}/go-pmtiles_{version}_Linux_x86_64.tar.gz"
        ),
        id="linux",
    ),
    pytest.param(
        "build_basemap.sh",
        lambda version: (
            "https://github.com/protomaps/go-pmtiles/releases/download/"
            f"v{version}/go-pmtiles-{version}_Darwin_x86_64.zip"
        ),
        id="macos",
    ),
    pytest.param(
        "build_basemap.ps1",
        lambda version: (
            "https://github.com/protomaps/go-pmtiles/releases/download/"
            f"v{version}/go-pmtiles_{version}_Windows_x86_64.zip"
        ),
        id="windows",
    ),
]


@pytest.mark.parametrize("script_name, url_builder", RELEASE_URL_CASES)
def test_pinned_pmtiles_release_asset_exists(script_name, url_builder):
    version = _pinned_version(_read(script_name))
    url = url_builder(version)

    assert _asset_exists(url), f"pmtiles release asset not found: {url}"
