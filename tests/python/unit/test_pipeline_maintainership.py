"""Tests for compose_orphans.pipeline.maintainership — fetch_maintainership."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from typing import TYPE_CHECKING

import pytest

from compose_orphans.exceptions import (
    NetworkTimeout,
    PipelineError,
    PipelineErrorReason,
)

if TYPE_CHECKING:
    from pathlib import Path

MAINTAINERSHIP_FETCH_FAILED = PipelineErrorReason.MAINTAINERSHIP_FETCH_FAILED
MAINTAINERSHIP_INVALID_JSON = PipelineErrorReason.MAINTAINERSHIP_INVALID_JSON

_DEFAULT_CONFIG_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Minimal Config stand-in
# ---------------------------------------------------------------------------


class _FakeConfig:
    timeout: int = _DEFAULT_CONFIG_TIMEOUT


_CONFIG = _FakeConfig()

# ---------------------------------------------------------------------------
# Helper: build an in-memory tar with a single file
# ---------------------------------------------------------------------------


def make_tar(filename: str, data: bytes) -> bytes:
    """Return bytes of a tar archive containing one file."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tf:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# FakeBinaryRunner
# ---------------------------------------------------------------------------


class FakeBinaryRunner:
    """Binary runner returning CompletedProcess[bytes]."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        raises: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._raises = raises

    def __call__(
        self,
        argv: list[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append({"argv": argv, "timeout": timeout, "cwd": cwd})
        if self._raises is not None:
            raise self._raises
        return subprocess.CompletedProcess(
            argv, self._returncode, self._stdout, self._stderr
        )


# ---------------------------------------------------------------------------
# Cycle 1: BinaryRunner importable from compose_orphans.runner
# ---------------------------------------------------------------------------


def test_binary_runner_protocol_in_runner_module() -> None:
    """BinaryRunner from compose_orphans.runner is runtime_checkable."""
    from compose_orphans.runner import BinaryRunner

    # Annotations are strings at runtime (from __future__ import annotations), so
    # Path does not need to be imported here — @runtime_checkable only checks __call__.
    def conforming(
        argv: list[str],
        *,
        timeout: int,
        cwd: None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    assert isinstance(conforming, BinaryRunner)


# ---------------------------------------------------------------------------
# Cycle 2: default_binary_runner returns bytes
# ---------------------------------------------------------------------------


def test_default_binary_runner_returns_bytes() -> None:
    """default_binary_runner stdout and stderr are bytes, not str."""
    from compose_orphans.runner import default_binary_runner

    proc = default_binary_runner(["echo", "hi"], timeout=5)
    assert isinstance(proc.stdout, bytes), (
        f"stdout should be bytes, got {type(proc.stdout).__name__}"
    )
    assert isinstance(proc.stderr, bytes), (
        f"stderr should be bytes, got {type(proc.stderr).__name__}"
    )


# ---------------------------------------------------------------------------
# Cycle 3: default_binary_runner never sets shell=True
# ---------------------------------------------------------------------------


def test_default_binary_runner_never_sets_shell_true() -> None:
    """default_binary_runner must not pass shell=True to subprocess.run."""
    import ast
    import inspect
    import textwrap

    from compose_orphans.runner import default_binary_runner

    source = textwrap.dedent(inspect.getsource(default_binary_runner))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "shell"
            and isinstance(node.value, ast.Constant)
        ):
            assert node.value.value is not True, (
                "default_binary_runner passes shell=True — critical security violation."
            )


# ---------------------------------------------------------------------------
# Cycle 4: fetch_maintainership success
# ---------------------------------------------------------------------------


def test_fetch_maintainership_success() -> None:
    """fetch_maintainership returns parsed dict on a valid in-memory tar."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    payload = {"packages": {"foo": {"users": ["alice"]}}}
    json_bytes = json.dumps(payload).encode()
    tar_bytes = make_tar("_maintainership.json", json_bytes)
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    result = fetch_maintainership(_CONFIG, runner=runner)
    assert result == payload


# ---------------------------------------------------------------------------
# Cycle 5: fetch_maintainership timeout → NetworkTimeout
# ---------------------------------------------------------------------------


def test_fetch_maintainership_timeout() -> None:
    """fetch_maintainership raises NetworkTimeout when runner raises TimeoutExpired."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    exc = subprocess.TimeoutExpired(["git"], 30)
    runner = FakeBinaryRunner(raises=exc)
    with pytest.raises(NetworkTimeout) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.__cause__ is exc


# ---------------------------------------------------------------------------
# Cycle 6: fetch_maintainership non-zero exit → PipelineError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_nonzero_exit() -> None:
    """fetch_maintainership raises PipelineError(FETCH_FAILED) on non-zero rc."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    runner = FakeBinaryRunner(returncode=128, stdout=b"", stderr=b"fatal: ...")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_FETCH_FAILED


# ---------------------------------------------------------------------------
# Cycle 7: fetch_maintainership tar payload too large → PipelineError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_tar_too_large() -> None:
    """fetch_maintainership raises PipelineError when stdout exceeds 50 MB."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    oversized = b"\x00" * (50 * 1024 * 1024 + 1)
    runner = FakeBinaryRunner(returncode=0, stdout=oversized, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_FETCH_FAILED


# ---------------------------------------------------------------------------
# Cycle 8: fetch_maintainership bad tar → PipelineError from TarError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_bad_tar() -> None:
    """fetch_maintainership raises PipelineError(FETCH_FAILED) with TarError cause."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    runner = FakeBinaryRunner(returncode=0, stdout=b"not a tar", stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_FETCH_FAILED
    assert isinstance(exc_info.value.__cause__, tarfile.TarError)


# ---------------------------------------------------------------------------
# Cycle 9: fetch_maintainership missing member → PipelineError from KeyError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_missing_member() -> None:
    """fetch_maintainership raises PipelineError when _maintainership.json absent."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    tar_bytes = make_tar("other.json", b'{"packages": {}}')
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_FETCH_FAILED
    assert isinstance(exc_info.value.__cause__, KeyError)


# ---------------------------------------------------------------------------
# Cycle 10: fetch_maintainership JSON payload too large → PipelineError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_json_too_large() -> None:
    """fetch_maintainership raises PipelineError when JSON bytes exceed 100 MB."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    big_json = b"x" * (100 * 1024 * 1024 + 1)
    tar_bytes = make_tar("_maintainership.json", big_json)
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_FETCH_FAILED


# ---------------------------------------------------------------------------
# Cycle 11: fetch_maintainership invalid JSON → PipelineError from JSONDecodeError
# ---------------------------------------------------------------------------


def test_fetch_maintainership_invalid_json() -> None:
    """fetch_maintainership raises PipelineError(INVALID_JSON) with JSONDecodeError."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    tar_bytes = make_tar("_maintainership.json", b"not json")
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_INVALID_JSON
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


# ---------------------------------------------------------------------------
# Cycle 12: wrong shape — not a dict → PipelineError(INVALID_JSON)
# ---------------------------------------------------------------------------


def test_fetch_maintainership_wrong_shape_not_dict() -> None:
    """fetch_maintainership raises PipelineError(INVALID_JSON) for non-dict root."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    tar_bytes = make_tar("_maintainership.json", b"[]")
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_INVALID_JSON


# ---------------------------------------------------------------------------
# Cycle 13: wrong shape — dict without 'packages' → PipelineError(INVALID_JSON)
# ---------------------------------------------------------------------------


def test_fetch_maintainership_wrong_shape_no_packages() -> None:
    """fetch_maintainership raises PipelineError(INVALID_JSON): no 'packages' key."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    tar_bytes = make_tar("_maintainership.json", b'{"other": 1}')
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert exc_info.value.reason == MAINTAINERSHIP_INVALID_JSON


# ---------------------------------------------------------------------------
# Cycle 14: exception chaining — TarError cause
# ---------------------------------------------------------------------------


def test_fetch_maintainership_exception_chaining_tar_error() -> None:
    """PipelineError __cause__ for bad tar is a tarfile.TarError instance."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    runner = FakeBinaryRunner(returncode=0, stdout=b"not a tar", stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert isinstance(exc_info.value.__cause__, tarfile.TarError)


# ---------------------------------------------------------------------------
# Cycle 15: exception chaining — JSONDecodeError cause
# ---------------------------------------------------------------------------


def test_fetch_maintainership_exception_chaining_json_error() -> None:
    """PipelineError __cause__ for invalid JSON is a json.JSONDecodeError instance."""
    from compose_orphans.pipeline.maintainership import fetch_maintainership

    tar_bytes = make_tar("_maintainership.json", b"not json")
    runner = FakeBinaryRunner(returncode=0, stdout=tar_bytes, stderr=b"")
    with pytest.raises(PipelineError) as exc_info:
        fetch_maintainership(_CONFIG, runner=runner)
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
