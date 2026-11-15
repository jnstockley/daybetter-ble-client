"""Release tags are validated before project metadata is changed."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prepare_release import parse_release_tag, prepare_release


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v1.2.3", "1.2.3"),
        ("V1.2.3", "1.2.3"),
        ("1.2.3", "1.2.3"),
        ("v1.2.3rc1", "1.2.3rc1"),
        ("v1.2.3.post1", "1.2.3.post1"),
    ],
)
def test_canonical_release_tags(tag, version):
    assert parse_release_tag(tag) == version


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "v",
        "release-1.2.3",
        "v1.2.3+local",
        "v01.2.3",
        "v1.2.3; echo nope",
        " v1.2.3",
        "--help",
    ],
)
def test_invalid_release_tags_are_rejected(tag):
    with pytest.raises(ValueError):
        parse_release_tag(tag)


def test_prepare_release_updates_metadata_in_an_isolated_project(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "release-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
    )
    lock = tmp_path / "uv.lock"
    lock.write_text("fixture lock must remain unchanged\n")
    assert prepare_release("v1.2.3", tmp_path) == "1.2.3"
    assert 'version = "1.2.3"' in project.read_text()
    assert lock.read_text() == "fixture lock must remain unchanged\n"


def test_invalid_tag_never_modifies_project(tmp_path):
    project = tmp_path / "pyproject.toml"
    original = '[project]\nname="fixture"\nversion="0.1.0"\n'
    project.write_text(original)
    with pytest.raises(ValueError):
        prepare_release("v1.2.3+local", tmp_path)
    assert project.read_text() == original


def test_release_cli_fails_without_modifying_project(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
    result = subprocess.run(
        [sys.executable, str(script), "not-a-version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "pyproject.toml").exists()
