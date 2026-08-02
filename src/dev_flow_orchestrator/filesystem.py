"""Private directory, lock and atomic-byte primitives for controller storage."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator, Tuple

from .model import DevFlowError


def ensure_private_directory(path: Path) -> None:
    try:
        if path.is_symlink():
            raise DevFlowError(
                "DATA_PATH_UNSAFE",
                "controller data directory must not be a symlink",
                details={"path": str(path)},
            )
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    except DevFlowError:
        raise
    except OSError as exc:
        raise DevFlowError(
            "DATA_PATH_FAILED",
            "controller data directory could not be prepared",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def _unsafe_path(path: Path) -> DevFlowError:
    return DevFlowError(
        "DATA_PATH_UNSAFE",
        "controller data path must not be a symlink or special file",
        details={"path": str(path)},
    )


def read_regular_file_at(root: Path, parts: Tuple[str, ...]) -> bytes:
    """Read a regular file through a no-follow descriptor chain."""
    if not parts:
        raise ValueError("relative file parts are required")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    descriptors = []
    target = root.joinpath(*parts)
    try:
        descriptor = os.open(str(root), directory_flags)
        descriptors.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | no_follow,
            dir_fd=descriptor,
        )
        descriptors.append(file_descriptor)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise _unsafe_path(target)
        with os.fdopen(file_descriptor, "rb", closefd=False) as stream:
            return stream.read()
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _unsafe_path(target) from exc
        raise
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


@contextlib.contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    ensure_private_directory(path.parent)
    try:
        descriptor = os.open(
            str(path),
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _unsafe_path(path) from exc
        raise DevFlowError(
            "STATE_LOCK_FAILED",
            "task lock could not be opened",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    locked = False
    try:
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise _unsafe_path(path)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
        except DevFlowError:
            raise
        except OSError as exc:
            raise DevFlowError(
                "STATE_LOCK_FAILED",
                "task lock could not be acquired",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = None
    descriptor = None
    try:
        ensure_private_directory(path.parent)
        if path.is_symlink():
            raise _unsafe_path(path)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".{}.write.".format(path.name),
            suffix=".tmp",
            dir=str(path.parent),
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise _unsafe_path(path)
        os.replace(str(temporary), str(path))
        os.chmod(path, 0o600)
        directory_descriptor = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except DevFlowError:
        raise
    except OSError as exc:
        raise DevFlowError(
            "STATE_WRITE_FAILED",
            "task state could not be atomically replaced",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
