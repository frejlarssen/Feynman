from __future__ import annotations

import datetime as dt
import hashlib
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .utils import iso_utc, run_capture


CMAKE_KEYS_OF_INTEREST = [
    "CMAKE_BUILD_TYPE",
    "CMAKE_GENERATOR",
    "CMAKE_CXX_COMPILER",
    "CMAKE_CXX_COMPILER_ID",
    "CMAKE_CXX_COMPILER_VERSION",
    "CMAKE_CXX_FLAGS",
    "CMAKE_CXX_FLAGS_RELEASE",
    "CMAKE_CXX_FLAGS_DEBUG",
    "MPI_CXX_COMPILER",
    "OpenMP_CXX_FLAGS",
]


def _run_git(repo_root: Path, *args: str) -> str:
    proc = run_capture(["git", "-C", str(repo_root), *args], cwd=repo_root)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _run_git_text(repo_root: Path, *args: str) -> str:
    proc = run_capture(["git", "-C", str(repo_root), *args], cwd=repo_root)
    if proc.returncode != 0:
        return ""
    return proc.stdout


def get_git_info(repo_root: Path) -> dict[str, Any]:
    return {
        "commit": _run_git(repo_root, "rev-parse", "HEAD"),
        "commit_short": _run_git(repo_root, "rev-parse", "--short", "HEAD"),
        "branch": _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(
            _run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
        ),
    }


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _path_for_metadata(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def describe_file(path: Path, repo_root: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": _path_for_metadata(path, repo_root),
        "size_bytes": stat.st_size,
        "mtime_utc": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "sha256": _sha256_file(path),
    }


def write_git_scope_snapshot(
    repo_root: Path,
    sweep_dir: Path,
    scope_paths: list[str],
    filename: str,
) -> dict[str, Any]:
    staged = _run_git_text(repo_root, "diff", "--cached", "--", *scope_paths)
    unstaged = _run_git_text(repo_root, "diff", "--", *scope_paths)
    untracked = _run_git_text(
        repo_root, "ls-files", "--others", "--exclude-standard", "--", *scope_paths
    )
    untracked_files = [line.strip() for line in untracked.splitlines() if line.strip()]

    lines: list[str] = [
        "# Git scope snapshot for experiment reproducibility",
        f"# paths: {', '.join(scope_paths)}",
        "",
        "## staged_diff",
        staged.rstrip() if staged.strip() else "# (no staged changes)",
        "",
        "## unstaged_diff",
        unstaged.rstrip() if unstaged.strip() else "# (no unstaged changes)",
        "",
        "## untracked_files",
    ]
    lines.extend(untracked_files if untracked_files else ["# (no untracked files)"])
    lines.append("")

    payload = "\n".join(lines)
    diff_path = sweep_dir / filename
    diff_path.write_text(payload, encoding="utf-8")

    payload_bytes = payload.encode("utf-8")
    return {
        "paths": scope_paths,
        "dirty": bool(staged.strip() or unstaged.strip() or untracked_files),
        "staged_has_changes": bool(staged.strip()),
        "unstaged_has_changes": bool(unstaged.strip()),
        "untracked_count": len(untracked_files),
        "diff_file": _path_for_metadata(diff_path, repo_root),
        "diff_file_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "diff_file_bytes": len(payload_bytes),
    }


def _find_cmake_cache(binary_path: Path, repo_root: Path) -> Path | None:
    for parent in [binary_path.parent, *binary_path.parents]:
        cache = parent / "CMakeCache.txt"
        if cache.exists():
            return cache
        if parent == repo_root:
            break
    return None


def _parse_cmake_cache(cache_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with cache_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if ":" not in line or "=" not in line:
                continue
            key_typed, value = line.split("=", 1)
            out[key_typed.split(":", 1)[0]] = value
    return out


def _build_metadata(binary_path: Path, repo_root: Path) -> dict[str, Any]:
    cache_path = _find_cmake_cache(binary_path, repo_root)
    if cache_path is None:
        return {
            "cmake_cache_found": False,
            "binary": describe_file(binary_path, repo_root),
        }

    cache = _parse_cmake_cache(cache_path)
    return {
        "cmake_cache_found": True,
        "cmake_cache_path": _path_for_metadata(cache_path, repo_root),
        "cmake_cache_sha256": _sha256_file(cache_path),
        "cmake_cache_size_bytes": cache_path.stat().st_size,
        "cmake": {k: cache.get(k, "") for k in CMAKE_KEYS_OF_INTEREST},
        "binary": describe_file(binary_path, repo_root),
    }


def _launcher_metadata(launcher_cmd: str, repo_root: Path) -> dict[str, Any]:
    tokens = shlex.split(launcher_cmd)
    if not tokens:
        return {
            "command": launcher_cmd,
            "version_ok": False,
            "version_probe": "",
            "returncode": -1,
            "output": "Empty launcher command.",
        }

    probes = [tokens + ["--version"], tokens + ["-V"]]
    last_error = ""
    for probe in probes:
        try:
            proc = run_capture(probe, repo_root)
        except OSError as err:
            last_error = str(err)
            continue
        combined = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0 and combined:
            return {
                "command": launcher_cmd,
                "version_ok": True,
                "version_probe": shlex.join(probe),
                "returncode": proc.returncode,
                "output": combined,
            }

    try:
        last = run_capture(probes[-1], repo_root)
    except OSError as err:
        return {
            "command": launcher_cmd,
            "version_ok": False,
            "version_probe": shlex.join(probes[-1]),
            "returncode": -1,
            "output": last_error or str(err),
        }
    return {
        "command": launcher_cmd,
        "version_ok": False,
        "version_probe": shlex.join(probes[-1]),
        "returncode": last.returncode,
        "output": (last.stdout + "\n" + last.stderr).strip(),
    }


def _system_command_metadata(command: list[str], repo_root: Path) -> dict[str, Any]:
    """Best-effort, bounded probes; retain diagnostics rather than abort a sweep."""
    result = {"command": command, "returncode": None, "stdout": "", "stderr": ""}
    try:
        proc = subprocess.run(
            command, cwd=repo_root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        result.update(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                      status="ok" if proc.returncode == 0 else "failed")
    except subprocess.TimeoutExpired as err:
        def decode(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        result.update(status="timeout", stdout=decode(err.stdout), stderr=decode(err.stderr))
    except OSError as err:
        result.update(status="unavailable" if isinstance(err, FileNotFoundError) else "failed",
                      error=str(err))
    return result


def _hardware_metadata(repo_root: Path) -> dict[str, Any]:
    logical_cores = os.cpu_count()
    system = platform.system()
    commands = {
        "uname": ["uname", "-a"],
        "df": ["df", "-h"],
        "uptime": ["uptime"],
    }
    if system == "Linux":
        commands.update({
            "lscpu": ["lscpu"],
            "nproc": ["nproc"],
            "free": ["free", "-h"],
            "lsblk": ["lsblk"],
            "os_release": ["cat", "/etc/os-release"],
        })
    elif system == "Darwin":
        commands.update({
            "sw_vers": ["sw_vers"],
            "sysctl_hardware": ["sysctl", "hw.model", "hw.machine", "hw.ncpu",
                                "hw.physicalcpu", "hw.logicalcpu", "hw.memsize"],
            "sysctl_cpu": ["sysctl", "machdep.cpu"],
            "vm_stat": ["vm_stat"],
        })
    probes = {name: _system_command_metadata(command, repo_root)
              for name, command in commands.items()}
    nproc_online = None
    nproc_error = ""
    nproc = probes.get("nproc")
    if nproc:
        token = nproc["stdout"].strip()
        if nproc["returncode"] == 0 and token.isdigit():
            nproc_online = int(token)
        else:
            nproc_error = nproc.get("error") or nproc["stderr"] or nproc["status"]
    return {
        "logical_cores_os_cpu_count": logical_cores,
        "logical_cores_nproc": nproc_online,
        "nproc_error": nproc_error,
        "scope": "local launcher host (not all MPI worker hosts)",
        "captured_at_utc": iso_utc(dt.datetime.now(dt.timezone.utc)),
        "system_commands": probes,
    }


def build_sweep_metadata(
    *,
    created_at: dt.datetime,
    repo_root: Path,
    sweep_dir: Path,
    git_scope_paths: list[str],
    git_scope_filename: str,
    git_scope_key: str,
    notes: str,
    invocation: str,
    dry_run: bool,
    git_info: dict[str, Any],
    binary_path: Path,
    input_files: dict[str, Path],
    runner_script_path: Path,
    launcher_command: str | None,
    launcher_key: str,
    config_snapshot: dict[str, Any],
) -> dict[str, Any]:
    git_scope_snapshot = write_git_scope_snapshot(
        repo_root=repo_root,
        sweep_dir=sweep_dir,
        scope_paths=git_scope_paths,
        filename=git_scope_filename,
    )
    inputs_meta = {name: describe_file(path, repo_root) for name, path in input_files.items()}

    provenance = {
        "build": _build_metadata(binary_path, repo_root),
        "inputs": inputs_meta,
        "runner_script": describe_file(runner_script_path.resolve(), repo_root),
    }
    if launcher_command is None:
        provenance["execution"] = {
            "mode": "direct",
            "executable": _path_for_metadata(binary_path, repo_root),
        }
    else:
        provenance[launcher_key] = _launcher_metadata(launcher_command, repo_root)

    return {
        "created_at_utc": iso_utc(created_at),
        "repo_root": str(repo_root),
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "git": {
            **git_info,
            git_scope_key: git_scope_snapshot,
        },
        "provenance": {
            **provenance,
            "hardware": _hardware_metadata(repo_root),
        },
        "notes": notes,
        "invocation": invocation,
        "config": config_snapshot,
        "environment": {
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", ""),
            "OMP_PROC_BIND": os.environ.get("OMP_PROC_BIND", ""),
            "OMP_PLACES": os.environ.get("OMP_PLACES", ""),
        },
        "dry_run": bool(dry_run),
    }
