"""Running projects: deploy, roll back, dump, and bring them back after a reboot.

In the bucket:
  releases/<project>/<tag>/compose.afp.yaml   put there by make deploy or the DevOps build
  releases/<project>/<tag>/source.tar.gz      the tag's source, put there by the DevOps build;
                                              when present, afp deploy builds the images on
                                              the VM and pushes them to OCIR (ADR 026)
  state/<project>.json                        {"current": tag, "previous": tag|null}
  dumps/<project>/<time>[-before-<tag>].sql.gz

Values for compose.afp.yaml (docs/04_using.md §3), secrets included, go to
docker compose through its environment; no env file is written.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from afp import db
from afp.config import BUCKET, Config, Project
from afp.errors import AfpError
from afp.log import utc_stamp

if TYPE_CHECKING:
    from afp.cli import Context

# Docker tag syntax.
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
WAIT_TIMEOUT = 300  # seconds for every service to become healthy
CADDY_PROJECT = "afp-caddy"
# Build cache older than this is removed after each build on the VM.
BUILD_CACHE_KEEP = "168h"


def check_tag(tag: str) -> None:
    if not TAG.match(tag):
        raise AfpError(f"invalid tag {tag!r} (must be usable as a Docker tag)")


def find(cfg: Config, name: str) -> Project:
    for p in cfg.projects:
        if p.name == name:
            return p
    raise AfpError(f"project {name!r} is not in afp.json")


def release_object(project: str, tag: str) -> str:
    return f"releases/{project}/{tag}/compose.afp.yaml"


def source_object(project: str, tag: str) -> str:
    return f"releases/{project}/{tag}/source.tar.gz"


def state_object(project: str) -> str:
    return f"state/{project}.json"


def registry(cfg: Config) -> str:
    return cfg.image_prefix_base.split("/", 1)[0]


def compose_env(cfg: Config, p: Project, tag: str, secrets: dict[str, str]) -> dict[str, str]:
    env = {name: value for name, value in secrets.items() if name != "AFP_DB_PASSWORD"}
    env.update(
        {
            "AFP_IMAGE_PREFIX": f"{cfg.image_prefix_base}/{p.name}",
            "AFP_TAG": tag,
            "AFP_PROJECT": p.name,
            "AFP_DOMAIN": p.domain,
            "AFP_DB_HOST": cfg.db.host,
            "AFP_DB_PORT": str(cfg.db.port),
            "AFP_DB_NAME": p.db_name,
            "AFP_DB_USER": p.db_name,
            "AFP_DB_PASSWORD": secrets["AFP_DB_PASSWORD"],
        }
    )
    return env


def build_services(config: dict[str, object], prefix: str) -> list[tuple[str, str]]:
    """Services with build:, and their OCIR repository names, from
    `docker compose config --format json`. Same rules as make deploy
    (scripts/rm_values.py build-services)."""
    result: list[tuple[str, str]] = []
    services = config.get("services") or {}
    if not isinstance(services, dict):
        raise AfpError("compose.afp.yaml: services must be a mapping")
    for name, service in sorted(services.items()):
        if not isinstance(service, dict) or "build" not in service:
            continue
        image = service.get("image") or ""
        path, _, tag = str(image).rpartition(":")
        if not str(image).startswith(prefix + "/") or not tag or "/" in tag:
            raise AfpError(f"service {name}: image must be ${{AFP_IMAGE_PREFIX}}/<name>:${{AFP_TAG}}, not {image!r}")
        result.append((name, path.split("/", 2)[2]))  # drop the registry host and the namespace
    if not result:
        raise AfpError("no service has build:; nothing to build")
    return result


def extract_source(archive: Path, dest: Path) -> None:
    """Unpack a source tar (git archive) into dest. Only plain files and
    directories inside dest are allowed: no links, devices or escaping paths."""
    with tarfile.open(archive, "r:*") as tar:
        members = tar.getmembers()
        for m in members:
            parts = Path(m.name).parts
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                raise AfpError(f"the source archive has an entry that is not allowed: {m.name!r}")
        dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, members=members, filter="data")
        else:  # pragma: no cover - Python without PEP 706; the checks above suffice
            tar.extractall(dest, members=members)


def parse_state(text: str | None) -> dict[str, str | None]:
    if text is None:
        return {"current": None, "previous": None}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise AfpError(f"the current-version state is not JSON: {e}") from e
    return {"current": data.get("current"), "previous": data.get("previous")}


def next_state(state: dict[str, str | None], tag: str) -> dict[str, str | None]:
    """After a successful deploy of tag. Deploying the current tag again keeps previous."""
    current = state["current"]
    return {"current": tag, "previous": state["previous"] if current == tag else current}


class Projects:
    """Operations on the projects of one afp run (one Context, one afp.json)."""

    def __init__(self, ctx: Context, cfg: Config) -> None:
        self.ctx = ctx
        self.cfg = cfg
        self.oci = ctx.need_oci()
        self._logged_in = False

    # --- bucket ------------------------------------------------------------

    def read_state(self, p: Project) -> dict[str, str | None]:
        return parse_state(self.oci.get_object_or_none(BUCKET, state_object(p.name)))

    def write_state(self, p: Project, state: dict[str, str | None]) -> None:
        path = self._work() / f"{p.name}.state.json"
        path.write_text(json.dumps(state) + "\n")
        self.oci.put_object(BUCKET, state_object(p.name), path, "application/json")
        path.unlink()

    def fetch_release(self, p: Project, tag: str) -> Path:
        text = self.oci.get_object_or_none(BUCKET, release_object(p.name, tag))
        if text is None:
            raise AfpError(f"no release {release_object(p.name, tag)} in the bucket; run make deploy")
        path = self.ctx.paths.projects_dir / p.name / tag / "compose.afp.yaml"
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def fetch_source(self, p: Project, tag: str) -> Path | None:
        """The tag's source archive in the work directory, or None if the
        release has none (make deploy built the images already)."""
        path = self._work() / f"{p.name}-{tag}-source.tar.gz"
        if self.oci.download_object(BUCKET, source_object(p.name, tag), path):
            return path
        path.unlink(missing_ok=True)
        return None

    def _work(self) -> Path:
        self.ctx.paths.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.ctx.paths.work_dir

    # --- secrets and registry ------------------------------------------------

    def secrets(self, p: Project) -> dict[str, str]:
        text = self.oci.secret(p.secret_id)
        values: dict[str, str] = {}
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise AfpError(f"the secret of project {p.name} is not a JSON object of strings")
        values.update(data)
        db.project_password(text, p.name)  # checks AFP_DB_PASSWORD
        for name, secret_id in p.manual_secret_ids.items():
            values[name] = self.oci.secret(secret_id)
        return values

    def login(self) -> None:
        """docker login to OCIR as the VM (the token lasts an hour)."""
        if self._logged_in:
            return
        host = registry(self.cfg)
        token = self.oci.registry_token(host)
        self.ctx.runner.run(["docker", "login", host, "-u", "BEARER_TOKEN", "--password-stdin"], stdin=token)
        self._logged_in = True

    # --- compose -------------------------------------------------------------

    def _compose(self, p: Project, path: Optional[Path] = None) -> list[str]:
        args = ["docker", "compose", "-p", p.name]
        return args + (["-f", str(path)] if path is not None else [])

    def up(self, p: Project, tag: str, secrets: dict[str, str]) -> None:
        """Pull and start tag; fail unless every service becomes healthy."""
        path = self.fetch_release(p, tag)
        env = compose_env(self.cfg, p, tag, secrets)
        self.login()
        self.ctx.runner.run([*self._compose(p, path), "pull", "-q"], env=env)
        self.ctx.runner.run(
            [*self._compose(p, path), "up", "-d", "--no-build", "--remove-orphans",
             "--wait", "--wait-timeout", str(WAIT_TIMEOUT)],
            env=env,
        )

    def build(self, p: Project, tag: str, archive: Path, secrets: dict[str, str]) -> None:
        """Build the services with build: from the tag's source, for the VM's
        own CPU type, and push them to OCIR."""
        if not self.cfg.compartment_id:
            raise AfpError("afp.json has no compartment_id; run make apply")
        src = self.ctx.paths.projects_dir / p.name / tag / "src"
        shutil.rmtree(src, ignore_errors=True)
        try:
            extract_source(archive, src)
            compose = src / "compose.afp.yaml"
            if not compose.is_file():
                raise AfpError(f"the source of {p.name} {tag} has no compose.afp.yaml")
            env = compose_env(self.cfg, p, tag, secrets)
            prefix = env["AFP_IMAGE_PREFIX"]
            result = self.ctx.runner.run([*self._compose(p, compose), "config", "--format", "json"], env=env, quiet=True)
            try:
                services = build_services(json.loads(result.stdout), prefix)
            except ValueError as e:
                raise AfpError(f"cannot read the services of {p.name} {tag}: {e}") from e
            for _, repository in services:
                self.oci.ensure_repository(self.cfg.compartment_id, repository)
            names = [name for name, _ in services]
            self.login()
            self.ctx.log.info(f"building {', '.join(names)} of {p.name} {tag}")
            self.ctx.runner.run([*self._compose(p, compose), "build", *names], env=env)
            self.ctx.runner.run([*self._compose(p, compose), "push", "--quiet", *names], env=env)
        finally:
            shutil.rmtree(src, ignore_errors=True)
            archive.unlink(missing_ok=True)
        # The layer cache makes the next build fast; keep it a week.
        self.ctx.runner.run(["docker", "builder", "prune", "-f", "--filter", f"until={BUILD_CACHE_KEEP}"], check=False, quiet=True)

    def down(self, name: str) -> None:
        self.ctx.runner.run(["docker", "compose", "-p", name, "down"])

    def running(self, p: Project) -> bool:
        result = self.ctx.runner.run(
            ["docker", "compose", "-p", p.name, "ps", "-q", "--status", "running"], quiet=True
        )
        return bool(result.stdout.strip())

    def compose_projects(self) -> list[str]:
        result = self.ctx.runner.run(["docker", "compose", "ls", "--all", "--format", "json"], quiet=True)
        try:
            return [item["Name"] for item in json.loads(result.stdout or "[]")]
        except (ValueError, KeyError, TypeError) as e:
            raise AfpError("cannot read docker compose ls") from e

    # --- DB dumps ------------------------------------------------------------

    def dump(self, p: Project, label: str = "") -> str:
        """Dump the project's database to the bucket; return the object name."""
        admin_password = self.oci.secret(self.cfg.db.admin_secret_id)
        work = self._work()
        raw = work / f"{p.name}.sql"
        packed = work / f"{p.name}.sql.gz"
        name = f"dumps/{p.name}/{utc_stamp()}{label}.sql.gz"
        try:
            self.ctx.runner.run(
                [
                    "docker", "run", "--rm", "-e", "MYSQL_PWD", db.mysql_image(self.ctx.paths.code),
                    "mysqldump", "-h", self.cfg.db.host, "-P", str(self.cfg.db.port), "-u", self.cfg.db.admin_user,
                    "--single-transaction", "--set-gtid-purged=OFF", "--no-tablespaces",
                    "--routines", "--triggers", "--databases", p.db_name,
                ],
                env={"MYSQL_PWD": admin_password},
                stdout_path=raw,
            )
            with open(raw, "rb") as src, gzip.open(packed, "wb") as dst:
                shutil.copyfileobj(src, dst)
            self.oci.put_object(BUCKET, name, packed, "application/gzip")
        finally:
            raw.unlink(missing_ok=True)
            packed.unlink(missing_ok=True)
        self.ctx.log.info(f"dumped {p.db_name} to {name}")
        return name

    # --- operations ----------------------------------------------------------

    def deploy(self, p: Project, tag: str, build: bool = True) -> str:
        """Deploy tag. With build, a release that has the tag's source is built
        first; a failed build changes nothing on the VM."""
        check_tag(tag)
        state = self.read_state(p)
        self.fetch_release(p, tag)  # fail before anything else if it is missing
        secrets = self.secrets(p)
        if build:
            archive = self.fetch_source(p, tag)
            if archive is not None:
                self.build(p, tag, archive, secrets)
        dump = self.dump(p, f"-before-{tag}")
        try:
            self.up(p, tag, secrets)
        except AfpError as e:
            current = state["current"]
            if current:
                self.ctx.log.info(f"{tag} failed; going back to {current}")
                try:
                    self.up(p, current, secrets)
                    after = f"back on {current}"
                except AfpError as e2:
                    after = f"going back to {current} failed too: {e2}"
            else:
                self.down(p.name)
                after = "stopped (no previous version)"
            raise AfpError(f"deploy of {p.name} {tag} failed: {e} -- {after}") from e
        new = next_state(state, tag)
        self.write_state(p, new)
        return f"{p.name} is now {tag} (previous: {new['previous'] or 'none'}); dump before it: {dump}"

    def rollback(self, p: Project) -> str:
        previous = self.read_state(p)["previous"]
        if not previous:
            raise AfpError(f"{p.name} has no previous version")
        result = self.deploy(p, previous, build=False)  # its images are in OCIR
        return f"{result}; the DB is not rolled back (dumps are in dumps/{p.name}/)"

    def start_stopped(self) -> list[str]:
        """Start each project's current version when none of it is running
        (a new or rebooted VM). Returns the names started."""
        started: list[str] = []
        failures: list[str] = []
        for p in self.cfg.projects:
            current = self.read_state(p)["current"]
            if not current or self.running(p):
                continue
            self.ctx.log.info(f"starting {p.name} {current}")
            try:
                self.up(p, current, self.secrets(p))
                started.append(p.name)
            except AfpError as e:
                failures.append(f"{p.name}: {e}")
        if failures:
            raise AfpError("could not start " + "; ".join(failures))
        return started

    def stop_removed(self) -> list[str]:
        """Stop the containers of projects no longer in afp.json (their DBs stay)."""
        names = {p.name for p in self.cfg.projects}
        stopped = [n for n in self.compose_projects() if n not in names and not n.startswith("afp")]
        for name in stopped:
            self.ctx.log.info(f"stopping {name}: no longer in afp.json")
            self.down(name)
        return stopped
