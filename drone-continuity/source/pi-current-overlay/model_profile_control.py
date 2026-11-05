"""Desktop model switching shares the AI-team lock; no flight-controller IO."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import time
import urllib.request

SERVICES = {
    'fast': ('orangepi-ai.service', 8080),
    'balanced': ('orangepi-ai-balanced.service', 8083),
    'quality': ('orangepi-ai-quality.service', 8081),
    'long': ('orangepi-ai-long.service', 8082),
}
LOCK = Path.home() / '.local/state/orangepi-model-orchestrator.lock'


@contextmanager
def model_lock(path=LOCK):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Refuse a redirected lock; use the same lock inode as the AI-team runner.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as handle:
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('AI review or model training is busy. Try again when it finishes.') from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def service(action, name, check=True):
    return subprocess.run(['systemctl', '--user', action, name], check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=30, text=True)


def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def wait_ready(port, timeout=300, probe=healthy, now=time.monotonic, pause=time.sleep):
    deadline = now() + timeout
    while now() < deadline:
        if probe(port):
            return
        pause(min(0.5, max(0, deadline - now())))
    raise TimeoutError('The model did not become healthy within its five-minute loading window.')


def switch_profile(profile, lock_path=LOCK, control=service, wait=wait_ready):
    if profile not in SERVICES:
        raise ValueError('Unknown fixed model profile')
    with model_lock(lock_path):
        target, port = SERVICES[profile]
        try:
            for name, _ in SERVICES.values():
                if name != target:
                    control('stop', name)
                    if control('is-active', name, check=False).returncode == 0:
                        raise RuntimeError('An earlier model is still active; refused concurrent loading.')
            control('start', target)
            wait(port)
        except Exception:
            # Do not leave a failed large-model load consuming the board's RAM.
            try:
                for name, _ in SERVICES.values():
                    control('stop', name)
                control('start', SERVICES['fast'][0])
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass  # Original failure is reported; live restore needs verification.
            raise
