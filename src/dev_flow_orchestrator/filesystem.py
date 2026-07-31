"""Private directory, lock and atomic-byte primitives for controller storage."""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import tempfile
from typing import Iterator

from .model import DevFlowError


def ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise DevFlowError(
            "DATA_PATH_UNSAFE",
            "controller data directory must not be a symlink",
            details={"path": str(path)},
        )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


@contextlib.contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    ensure_private_directory(path.parent)
    descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}.write.".format(path.name),
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        os.chmod(path, 0o600)
        directory_descriptor = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
