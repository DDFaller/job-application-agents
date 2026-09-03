#!/usr/bin/env python3
"""Guided, repeatable setup for the Job Application Agents plugin."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import venv
from pathlib import Path


PLUGIN_NAME = "job-application-agents"
MARKETPLACE_NAME = "personal"
REQUIRED_TOOLS = ("python3", "codex")
# The local-first renderer and the VS Code LaTeX Workshop integration share
# this toolchain.  Keep these separate from REQUIRED_TOOLS because the
# containerized worker can still render for a cloud-only installation.
LOCAL_LATEX_TOOLS = ("latexmk", "xelatex", "kpsewhich", "pdfinfo", "pdftotext")
HUMANIZER_LOCK = Path("skills") / "humanizer.lock.json"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def missing_local_latex_tools() -> list[str]:
    return [tool for tool in LOCAL_LATEX_TOOLS if not command_exists(tool)]


def local_latex_install_commands(missing: list[str]) -> list[list[str]]:
    """Return explicit package-manager commands for missing local build tools."""
    if not missing:
        return []
    package_map = {
        "latexmk": "latexmk",
        "xelatex": "texlive-xetex",
        "kpsewhich": "texlive-xetex",
        "pdfinfo": "poppler-utils",
        "pdftotext": "poppler-utils",
    }
    if command_exists("dnf"):
        packages = sorted({package_map[tool] for tool in missing})
        return [["sudo", "dnf", "install", "-y", *packages]]
    if command_exists("apt-get"):
        packages = sorted({package_map[tool] for tool in missing})
        return [["sudo", "apt-get", "install", "-y", *packages]]
    if command_exists("brew"):
        # Homebrew's mactex cask supplies the TeX engine and latexmk together;
        # Poppler is the only separate command in the local quality checks.
        commands: list[list[str]] = []
        if any(tool in {"latexmk", "xelatex", "kpsewhich"} for tool in missing):
            commands.append(["brew", "install", "--cask", "mactex-no-gui"])
        if any(tool in {"pdfinfo", "pdftotext"} for tool in missing):
            commands.append(["brew", "install", "poppler"])
        return commands
    return []


def local_latex_install_hint(missing: list[str]) -> str:
    """Return a copyable package-manager command for missing local tools."""
    commands = local_latex_install_commands(missing)
    if commands:
        return " && ".join(" ".join(command) for command in commands)
    return "install the missing tools with your OS package manager: " + ", ".join(missing)


def docker_compose_ready() -> bool:
    if not command_exists("docker"):
        return False
    return subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, check=False
    ).returncode == 0


def install_python_runtime(repo: Path, *, cloud: bool = False) -> Path:
    environment = repo / ".venv"
    python = environment / "bin" / "python"
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    package = f"{repo}[cloud]" if cloud else str(repo)
    subprocess.run([str(python), "-m", "pip", "install", package], check=True)
    return python


def load_humanizer_lock(repo: Path) -> dict[str, str]:
    path = repo / HUMANIZER_LOCK
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "version", "skill_url", "skill_sha256", "license_url", "license_sha256"}
    if set(value) != required or value.get("name") != "humanizer":
        raise ValueError(f"invalid Humanizer lock file: {path}")
    if not re.fullmatch(r"[0-9a-f]{64}", value["skill_sha256"]) or not re.fullmatch(r"[0-9a-f]{64}", value["license_sha256"]):
        raise ValueError(f"Humanizer lock file has invalid checksums: {path}")
    return value


def validate_humanizer_payload(payload: bytes, lock: dict[str, str]) -> None:
    if hashlib.sha256(payload).hexdigest() != lock["skill_sha256"]:
        raise ValueError("downloaded Humanizer skill checksum does not match the lock")
    text = payload.decode("utf-8")
    match = re.search(r"^\s*version:\s*[\"']([^\"']+)[\"']\s*$", text, re.MULTILINE)
    if not match or match.group(1) != lock["version"]:
        raise ValueError("downloaded Humanizer skill version does not match the lock")


def install_humanizer_skill(repo: Path, plugin: Path) -> tuple[Path, str]:
    """Install the pinned upstream Markdown skill into the copied plugin."""
    lock = load_humanizer_lock(repo)
    target_dir = plugin / "skills" / "humanizer"
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_path = target_dir / "SKILL.md"
    license_path = target_dir / "LICENSE"
    if skill_path.is_symlink() or license_path.is_symlink():
        raise ValueError("Humanizer install refuses symlink targets")
    if skill_path.is_file() and license_path.is_file():
        skill = skill_path.read_bytes()
        license_bytes = license_path.read_bytes()
        validate_humanizer_payload(skill, lock)
        if hashlib.sha256(license_bytes).hexdigest() != lock["license_sha256"]:
            raise ValueError("installed Humanizer license checksum does not match the lock")
        return skill_path, lock["version"]

    with urllib.request.urlopen(lock["skill_url"], timeout=30) as response:
        skill = response.read()
    with urllib.request.urlopen(lock["license_url"], timeout=30) as response:
        license_bytes = response.read()
    validate_humanizer_payload(skill, lock)
    if hashlib.sha256(license_bytes).hexdigest() != lock["license_sha256"]:
        raise ValueError("downloaded Humanizer license checksum does not match the lock")
    for path, payload in ((skill_path, skill), (license_path, license_bytes)):
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=target_dir)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return skill_path, lock["version"]


def humanizer_lock_ready(repo: Path) -> tuple[bool, str]:
    try:
        lock = load_humanizer_lock(repo)
        return True, f"Humanizer skill installer (v{lock['version']})"
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"Humanizer skill installer: {exc}"


def ask(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, check=check)


def copy_plugin(repo: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(".git", ".agents", ".codex", ".venv", "__pycache__", "*.pyc", "applications", "sources", "master-curriculum")
    temporary = Path(tempfile.mkdtemp(prefix=f".{PLUGIN_NAME}-", dir=destination.parent))
    try:
        shutil.copytree(repo, temporary / PLUGIN_NAME, ignore=ignored)
        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = destination.with_name(destination.name + f".previous-{stamp}-{os.getpid()}")
            destination.replace(backup)
        (temporary / PLUGIN_NAME).replace(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def update_marketplace(home: Path) -> tuple[Path, str]:
    path = home / ".agents" / "plugins" / "marketplace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("plugins", []), list):
            raise ValueError(f"invalid personal marketplace: {path}")
    else:
        data = {"name": MARKETPLACE_NAME, "interface": {"displayName": "Personal"}, "plugins": []}
    marketplace_name = data.get("name")
    if not isinstance(marketplace_name, str) or not marketplace_name:
        raise ValueError(f"personal marketplace has no valid name: {path}")
    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./.codex/plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    data["plugins"] = [item for item in data["plugins"] if item.get("name") != PLUGIN_NAME] + [entry]
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path, marketplace_name


def first_party_scripts(plugin: Path) -> list[Path]:
    paths = list((plugin / "scripts").glob("*.py"))
    paths.extend(plugin.glob("skills/*/scripts/*.py"))
    return sorted(path.resolve() for path in paths if not path.name.startswith("test_"))


def write_rules(home: Path, plugins: list[Path]) -> Path:
    path = home / ".codex" / "rules" / f"{PLUGIN_NAME}.rules"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by job-application-agents/scripts/setup.py."]
    scripts = sorted({script for plugin in plugins for script in first_party_scripts(plugin)})
    for script in scripts:
        lines.extend([
            "prefix_rule(",
            f"    pattern = [\"python3\", {json.dumps(str(script))}],",
            "    decision = \"allow\",",
            "    justification = \"Run a bundled job-application validator or renderer.\",",
            f"    match = [{json.dumps('python3 ' + str(script) + ' --help')}],",
            ")",
            "",
        ])
    temporary = path.with_suffix(".rules.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
    return path


def readiness(
    repo: Path,
    data_root: Path,
    *,
    require_local_latex: bool = True,
    cloud: bool = False,
) -> tuple[list[str], list[str]]:
    ready: list[str] = []
    blocked: list[str] = []
    for tool in REQUIRED_TOOLS:
        (ready if command_exists(tool) else blocked).append(f"tool: {tool}")
    missing_latex = missing_local_latex_tools()
    for tool in LOCAL_LATEX_TOOLS:
        label = f"local LaTeX tool: {tool}"
        (ready if tool not in missing_latex else blocked).append(label)
    if missing_latex and not require_local_latex:
        for tool in missing_latex:
            blocked.remove(f"local LaTeX tool: {tool}")
    if cloud:
        (ready if docker_compose_ready() else blocked).append("Docker Compose")
    runtime = repo / ".venv" / "bin" / "python"
    runtime_check = "import job_application_agents"
    if cloud:
        runtime_check += "; import firebase_admin"
    if runtime.is_file() and subprocess.run(
        [str(runtime), "-c", runtime_check], capture_output=True, text=True, check=False
    ).returncode == 0:
        ready.append("Python render-service runtime")
    else:
        blocked.append("Python render-service runtime")
    if (repo / ".codex-plugin" / "plugin.json").is_file():
        ready.append("plugin manifest")
    else:
        blocked.append("plugin manifest")
    humanizer_ready, humanizer_status = humanizer_lock_ready(repo)
    (ready if humanizer_ready else blocked).append(humanizer_status)
    if data_root.is_dir():
        ready.append(f"data root: {data_root}")
    else:
        blocked.append(f"data root: {data_root}")
    return ready, blocked


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--check", action="store_true", help="diagnose without changing anything")
    result.add_argument(
        "--skip-local-latex",
        action="store_true",
        help="allow a cloud-only setup without the local LaTeX/VS Code toolchain (requires --cloud)",
    )
    result.add_argument(
        "--cloud",
        action="store_true",
        help="opt into Docker/Firebase cloud-worker dependencies and checks",
    )
    result.add_argument("--data-root", type=Path, default=Path.home() / "Documents" / "job-search")
    result.add_argument("--skip-notion-login", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.skip_local_latex and not args.cloud:
        print("BLOCKED --skip-local-latex is only valid with explicit --cloud", file=sys.stderr)
        return 1
    repo = Path(__file__).resolve().parent.parent
    data_root = args.data_root.expanduser().resolve()
    print(f"Job Application Agents setup ({platform.system()})")
    if args.check:
        ready, blocked = readiness(
            repo,
            data_root,
            require_local_latex=not args.skip_local_latex,
            cloud=args.cloud,
        )
        for item in ready:
            print(f"READY   {item}")
        for item in blocked:
            print(f"BLOCKED {item}")
        missing_latex = missing_local_latex_tools()
        if missing_latex and not args.skip_local_latex:
            print(f"NEXT    Install local LaTeX tools: {local_latex_install_hint(missing_latex)}")
        return 1 if blocked else 0

    missing = [name for name in REQUIRED_TOOLS if not command_exists(name)]
    missing_latex = missing_local_latex_tools() if not args.skip_local_latex else []
    if missing_latex:
        print(
            "BLOCKED Local LaTeX editing/build tools are missing: " + ", ".join(missing_latex),
            file=sys.stderr,
        )
        print(f"NEXT Install them with: {local_latex_install_hint(missing_latex)}", file=sys.stderr)
        commands = local_latex_install_commands(missing_latex)
        if commands and ask("Install the missing local LaTeX dependencies now?"):
            try:
                for command in commands:
                    run(command)
            except (OSError, subprocess.CalledProcessError) as exc:
                print(f"BLOCKED Could not install local LaTeX dependencies: {exc}", file=sys.stderr)
                return 1
            missing_latex = missing_local_latex_tools()
    missing_runtime = [*missing]
    if args.cloud and not docker_compose_ready():
        missing_runtime.append("Docker Compose")
    if missing_runtime or missing_latex:
        if missing_latex:
            print(
                "BLOCKED Local LaTeX editing/build tools are missing: " + ", ".join(missing_latex),
                file=sys.stderr,
            )
            print(f"NEXT Install them with: {local_latex_install_hint(missing_latex)}", file=sys.stderr)
        if missing_runtime:
            print(
                "BLOCKED Install the missing runtime tools: " + ", ".join(missing_runtime),
                file=sys.stderr,
            )
        if args.skip_local_latex:
            print("NEXT    Set JAA_RENDER_MODE=cloud when running without local LaTeX tools.")
        return 1

    for directory in ("sources", "applications", "master-curriculum", "applications/.workflow-runs"):
        (data_root / directory).mkdir(parents=True, exist_ok=True)
    try:
        runtime_python = install_python_runtime(repo, cloud=args.cloud)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"BLOCKED Could not install the Python render-service runtime: {exc}", file=sys.stderr)
        return 1
    home = Path.home()
    plugin = home / ".codex" / "plugins" / PLUGIN_NAME
    plugin.parent.mkdir(parents=True, exist_ok=True)
    copy_plugin(repo, plugin)
    try:
        humanizer_path, humanizer_version = install_humanizer_skill(repo, plugin)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"BLOCKED Could not install pinned Humanizer skill: {exc}", file=sys.stderr)
        return 1
    marketplace, marketplace_name = update_marketplace(home)
    result = subprocess.run(["codex", "plugin", "add", f"{PLUGIN_NAME}@{marketplace_name}"], text=True)
    if result.returncode:
        print("Plugin registration needs attention; rerun setup after resolving the Codex message above.", file=sys.stderr)
    cache_roots = [path for path in (home / ".codex" / "plugins" / "cache").glob(f"*/{PLUGIN_NAME}/*") if path.is_dir()]
    rules = write_rules(home, [repo, plugin, *cache_roots])
    if not args.skip_notion_login and ask("Connect Notion now in your browser?"):
        subprocess.run(["codex", "mcp", "login", "notion"], text=True)
    if args.cloud and ask("Start the optional Firestore emulator and XeLaTeX worker now?"):
        subprocess.run([
            str(runtime_python), str(repo / "scripts" / "render_service.py"),
            "up", "--data-root", str(data_root),
        ], text=True)

    print(f"READY   data root: {data_root}")
    print(f"READY   personal marketplace: {marketplace}")
    print(f"READY   scoped command rules: {rules}")
    print(f"READY   Python runtime: {runtime_python}")
    print(f"READY   Humanizer skill v{humanizer_version}: {humanizer_path}")
    if args.skip_local_latex:
        print("NEXT    Set JAA_RENDER_MODE=cloud for rendering without local LaTeX tools.")
    elif args.cloud:
        print("NEXT    Start optional cloud services when needed: .venv/bin/python scripts/render_service.py up --cloud")
    else:
        print("READY   default mode: local rendering + Notion status tracking")
    print("NEXT    Restart Codex, then run: python3 scripts/launch.py")
    print("NEXT    Ask: Prepare this job application: <public job URL>")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
