"""Tests for scripts/devops-release.sh with a fake `oci` and a real git repository."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "devops-release.sh"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "compose.afp.yaml").write_text("services: {}\n")
    (repo / "app.py").write_text("print(1)\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Fake oci: copies each put object to puts/<name>.
    (bin_dir / "oci").write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{tmp_path}/oci.log"\n'
        'while [ $# -gt 0 ]; do case "$1" in --name) n="$2"; shift;; --file) f="$2"; shift;; esac; shift; done\n'
        f'mkdir -p "{tmp_path}/puts/$(dirname "$n")" && cp "$f" "{tmp_path}/puts/$n"\n'
    )
    (bin_dir / "oci").chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "AFP_PROJECT": "hello",
            "AFP_BUCKET": "afp", "OCI_PRIMARY_SOURCE_DIR": str(repo)}


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_releases_the_tag_of_the_commit(env: dict[str, str], tmp_path: Path) -> None:
    git(tmp_path / "project", "tag", "v1.2.0")
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "v1.2.0\n"  # only the tag on stdout, for AFP_TAG
    puts = tmp_path / "puts" / "releases" / "hello" / "v1.2.0"
    assert (puts / "compose.afp.yaml").read_text() == "services: {}\n"
    with tarfile.open(puts / "source.tar.gz") as tar:
        assert sorted(tar.getnames()) == ["app.py", "compose.afp.yaml"]
    log = (tmp_path / "oci.log").read_text().splitlines()
    assert "source.tar.gz" in log[0] and "compose.afp.yaml" in log[1]  # the source first


def test_releases_an_annotated_tag(env: dict[str, str], tmp_path: Path) -> None:
    git(tmp_path / "project", "tag", "-a", "v2", "-m", "v2")
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "v2\n"


def test_ignores_tags_that_are_not_v(env: dict[str, str], tmp_path: Path) -> None:
    git(tmp_path / "project", "tag", "nightly")
    git(tmp_path / "project", "tag", "v3")
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "v3\n"


def test_refuses_a_commit_without_a_tag(env: dict[str, str], tmp_path: Path) -> None:
    result = run(env)
    assert result.returncode == 1
    assert "no tag v*" in result.stderr
    assert "git push --atomic origin HEAD:release" in result.stderr
    assert not (tmp_path / "oci.log").exists()


def test_refuses_a_commit_with_several_tags(env: dict[str, str], tmp_path: Path) -> None:
    git(tmp_path / "project", "tag", "v9")
    git(tmp_path / "project", "tag", "v10")
    result = run(env)
    assert result.returncode == 1
    assert "several tags v*" in result.stderr and "v10" in result.stderr and "v9" in result.stderr
    assert not (tmp_path / "oci.log").exists()


def test_uses_only_the_tags_of_the_commit_under_build(env: dict[str, str], tmp_path: Path) -> None:
    repo = tmp_path / "project"
    git(repo, "tag", "v1")
    (repo / "app.py").write_text("print(2)\n")
    git(repo, "commit", "-q", "-am", "two")
    result = run(env)
    assert result.returncode == 1  # v1 is on the previous commit
    assert "no tag v*" in result.stderr


@pytest.mark.parametrize("tag", ["v1;reboot", "v1'", "v1$(id)"])
def test_refuses_tags_that_are_not_docker_tags(env: dict[str, str], tmp_path: Path, tag: str) -> None:
    git(tmp_path / "project", "tag", tag)
    result = run(env)
    assert result.returncode == 1
    assert not (tmp_path / "oci.log").exists()


def test_needs_compose_afp_yaml(env: dict[str, str], tmp_path: Path) -> None:
    repo = tmp_path / "project"
    git(repo, "rm", "-q", "compose.afp.yaml")
    git(repo, "commit", "-q", "-m", "two")
    git(repo, "tag", "v3")
    result = run(env)
    assert result.returncode == 1
    assert "compose.afp.yaml" in result.stderr


def test_example_build_spec_calls_the_script() -> None:
    text = (ROOT / "examples" / "hello" / "build_spec.yaml").read_text()
    assert "exportedVariables:\n    - AFP_TAG" in text
    assert 'AFP_TAG="$(/tmp/afp-platform/scripts/devops-release.sh)"' in text
