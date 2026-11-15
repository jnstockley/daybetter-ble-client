"""Set the distribution version from a canonical GitHub release tag."""

import argparse
import subprocess
from pathlib import Path

from packaging.version import Version


def parse_release_tag(tag: str) -> str:
    """Accept canonical public PEP 440 versions with an optional v/V prefix."""
    value = tag[1:] if tag.startswith(("v", "V")) else tag
    version = Version(value)
    if version.local is not None or str(version) != value:
        raise ValueError("Release tag must contain a canonical public PEP 440 version")
    return str(version)


def prepare_release(tag: str, project_dir: Path) -> str:
    """Update only the release checkout, without changing its lock or environment."""
    version = parse_release_tag(tag)
    subprocess.run(
        ["uv", "version", "--frozen", "--", version],
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="GitHub release tag, for example v0.4.0")
    args = parser.parse_args()
    print(prepare_release(args.tag, Path.cwd()))


if __name__ == "__main__":
    main()
