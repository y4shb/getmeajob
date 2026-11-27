"""Shared test setup.

- The network is blocked: only 127.0.0.1 and ::1 (and local unix sockets) may be used.
  Use `FixtureTransport` or `httpx.MockTransport` instead.
- getmeajob environment variables from the developer's shell are cleared.
- Fixtures: `tmp_ws` (an empty workspace with its folders made, no profile.yaml)
  and `demo_ws` (a workspace made by `getmeajob init --demo`).

Test files may share names across folders (pytest runs with --import-mode=importlib);
share helpers through fixtures here rather than by importing test modules.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from getmeajob.cli import main
from getmeajob.workspace import Workspace

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", None}
OWN_ENV = ("GETMEAJOB_HOME", "GETMEAJOB_FIXTURES", "GETMEAJOB_DENYLIST", "GETMEAJOB_LLM_COMMAND")


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to reach a host other than this machine."""


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _check_address(sock: socket.socket, address: Any) -> None:
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "::1"):
        raise NetworkBlocked(f"tests must not use the network (tried to connect to {address!r})")


def _guarded_connect(self: socket.socket, address: Any) -> None:
    _check_address(self, address)
    _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    _check_address(self, address)
    return _real_connect_ex(self, address)


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    name = host.decode() if isinstance(host, bytes) else host
    if name not in LOCAL_HOSTS:
        raise NetworkBlocked(f"tests must not use the network (tried to look up {name!r})")
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _block_network() -> Iterator[None]:
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _guarded_getaddrinfo
    try:
        yield
    finally:
        socket.socket.connect = _real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _real_getaddrinfo


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in OWN_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def tmp_ws(tmp_path: Path) -> Workspace:
    """An empty workspace in a temp folder with all its folders created."""
    ws = Workspace(tmp_path / "ws")
    ws.ensure_dirs()
    return ws


@pytest.fixture
def demo_ws(tmp_path: Path) -> Workspace:
    """A workspace created by `getmeajob init --demo --home <tmp>`."""
    root = tmp_path / "demo"
    assert main(["init", "--demo", "--home", str(root), "--quiet"]) == 0
    return Workspace.resolve(root)
