"""Windows-friendly one-command ValiGuard launcher."""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
BACKEND_URL = "http://127.0.0.1:5000"
FRONTEND_URL = "http://127.0.0.1:3001"
REQUIRED_DEPENDENCIES = ("requests", "flask", "flask_socketio")


def get_venv_python() -> Optional[Path]:
    """Return the interpreter path inside the project's venv, if it exists."""
    if os.name == "nt":
        candidate = VENV_DIR / "Scripts" / "python.exe"
    else:
        candidate = VENV_DIR / "bin" / "python"
    return candidate if candidate.is_file() else None


def get_python_exe() -> Path:
    """Return the project venv python if available, else current sys.executable."""
    venv_python = get_venv_python()
    if venv_python is not None:
        return venv_python
    return Path(sys.executable)


def is_running_in_project_venv() -> bool:
    """Check if the current process is already executing inside the project venv."""
    venv_resolved = VENV_DIR.resolve()
    try:
        if Path(sys.prefix).resolve() == venv_resolved:
            return True
    except OSError:
        pass
    venv_python = get_venv_python()
    if venv_python:
        try:
            if Path(sys.executable).resolve() == venv_python.resolve():
                return True
        except OSError:
            pass
    return False


def maybe_reexec_into_venv() -> None:
    """Re-exec into the project venv if one exists and we are not already using it."""
    if os.environ.get("VALIGUARD_REEXEC") == "1":
        return
    if is_running_in_project_venv():
        return
    venv_python = get_venv_python()
    if not venv_python:
        return

    print(f"[*] Re-executing launcher using project venv: {venv_python}")
    env = dict(os.environ)
    env["VALIGUARD_REEXEC"] = "1"
    cmd = [str(venv_python), str(ROOT / "start_project.py")] + sys.argv[1:]
    if os.name != "nt":
        os.execve(str(venv_python), cmd, env)
    else:
        try:
            exit_code = subprocess.call(cmd, env=env)
            sys.exit(exit_code)
        except KeyboardInterrupt:
            sys.exit(0)


def check_dependencies(modules: tuple[str, ...] = REQUIRED_DEPENDENCIES) -> None:
    """Dependency preflight: verify required packages can be imported without traceback."""
    missing = []
    for mod in modules:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        venv_hint = (
            r".\venv\Scripts\python.exe start_project.py"
            if os.name == "nt"
            else "./venv/bin/python start_project.py"
        )
        print(
            f"Dependencies missing — run 'pip install -r requirements.txt' or use the project venv: {venv_hint}",
            file=sys.stderr,
        )
        sys.exit(1)


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the ValiGuard local stack")
    parser.add_argument("--demo", action="store_true", help="disable QIE ingestion")
    parser.add_argument("--simulate", action="store_true", help="run HTTP traffic simulator")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def configure_environment(demo: bool, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    environment = dict(base or os.environ)
    if demo:
        environment["VALIGUARD_INGESTION_WORKER"] = "0"
        environment["NEXT_PUBLIC_DEMO_MODE"] = "true"
    else:
        environment.setdefault("VALIGUARD_INGESTION_WORKER", "1")
        environment.setdefault("MEMPOOL_ENABLED", "1")
        environment.setdefault("NEXT_PUBLIC_DEMO_MODE", "false")
    return environment


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_port_pid(port: int) -> Optional[str]:
    """Best-effort PID lookup for whatever holds a port (Windows netstat)."""
    if os.name != "nt":
        return None
    try:
        output = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, check=False,
        ).stdout
    except OSError:
        return None
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[-2] == "LISTENING":
            return parts[-1]
    return None


def check_ports_free() -> None:
    """Fail fast with the port AND the likely owning PID on conflicts."""
    for port, label in ((5000, "backend API (Flask)"), (3001, "frontend (Next.js)")):
        if port_in_use(port):
            pid = find_port_pid(port)
            hint = f" (likely PID {pid})" if pid else ""
            raise RuntimeError(
                f"Port {port} is already in use by the {label}{hint}; "
                f"stop that process first (taskkill /PID {pid} /T /F)"
                if pid else
                f"Port {port} is already in use by the {label}; "
                "stop that process first"
            )


def wait_for_http(url: str, timeout: float, label: str) -> None:
    global requests
    if requests is None:
        import requests as _requests
        requests = _requests

    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=1)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"{label} did not become healthy at {url}: {last_error}")


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()


def spawn(command: List[str], cwd: Path, env: Dict[str, str], label: str) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    print(f"[*] Starting {label}...")
    return subprocess.Popen(command, cwd=cwd, env=env, creationflags=creationflags)


def run_migrations(env: Dict[str, str]) -> None:
    python_exe = get_python_exe()
    result = subprocess.run(
        [str(python_exe), "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=env,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Alembic migration failed")


def main(argv: Optional[List[str]] = None) -> int:
    check_dependencies()
    args = build_parser().parse_args(argv)
    load_dotenv()
    env = configure_environment(args.demo)

    check_ports_free()

    run_migrations(env)
    python_exe = get_python_exe()
    npm = "npm.cmd" if os.name == "nt" else "npm"
    processes: List[subprocess.Popen] = []

    # Reap children even if main() exits through an unexpected path (not a
    # hard SIGKILL — nothing can recover from that; see README).
    atexit.register(cleanup_for_tests, processes)

    try:
        processes.append(spawn([str(python_exe), "-m", "backend.app"], ROOT, env, "backend"))
        wait_for_http(f"{BACKEND_URL}/health", 30, "backend")
        processes.append(spawn([npm, "run", "dev"], ROOT / "frontend", env, "frontend"))
        wait_for_http(FRONTEND_URL, 45, "frontend")
        if args.simulate:
            processes.append(spawn(
                [str(python_exe), "scripts/generate_mock_traffic.py", "--api-url", BACKEND_URL],
                ROOT,
                env,
                "traffic simulator",
            ))
        print("\nValiGuard is running")
        print(f"  Dashboard: {FRONTEND_URL}")
        print(f"  API:       {BACKEND_URL}")
        print(f"  Health:    {BACKEND_URL}/health")
        print(f"  Mode:      {'demo (no QIE node — node status shows offline honestly)' if args.demo else 'QIE (worker + mempool enabled)'}{' + traffic simulator' if args.simulate else ''}")
        if not args.no_browser:
            import webbrowser
            webbrowser.open(FRONTEND_URL)
        while True:
            time.sleep(1)
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A child process exited unexpectedly")
    except KeyboardInterrupt:
        print("\nStopping ValiGuard...")
        return 0
    finally:
        for process in reversed(processes):
            terminate_process(process)


def cleanup_for_tests(processes: List[subprocess.Popen]) -> None:
    """Test helper documenting the same Windows taskkill cleanup path."""
    for process in reversed(processes):
        terminate_process(process)


if __name__ == "__main__":
    maybe_reexec_into_venv()
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[x] {exc}", file=sys.stderr)
        raise SystemExit(1)
