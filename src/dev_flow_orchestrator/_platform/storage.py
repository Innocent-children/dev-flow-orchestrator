"""Host-specific directory, lock, read, listing, and replacement primitives."""

from __future__ import annotations

import contextlib
import errno
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Iterator, Tuple

from ..model import DevFlowError

if os.name == "nt":  # pragma: no cover - imported and exercised on Windows CI
    import msvcrt
else:
    import fcntl


def _unsafe_path(path: Path) -> DevFlowError:
    return DevFlowError(
        "DATA_PATH_UNSAFE",
        "controller data path must not be a symlink or special file",
        details={"path": str(path)},
    )


def ensure_private_directory(path: Path) -> None:
    try:
        if path.is_symlink():
            raise DevFlowError(
                "DATA_PATH_UNSAFE",
                "controller data directory must not be a symlink",
                details={"path": str(path)},
            )
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise _unsafe_path(path)
        if os.name != "nt":
            os.chmod(path, 0o700)
    except DevFlowError:
        raise
    except OSError as exc:
        raise DevFlowError(
            "DATA_PATH_FAILED",
            "controller data directory could not be prepared",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def _windows_target(root: Path, parts: Tuple[str, ...]) -> Path:
    return root.joinpath(*parts)


def _windows_read_regular_file(root: Path, parts: Tuple[str, ...]) -> bytes:
    target = _windows_target(root, parts)
    metadata = target.lstat()
    if target.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise _unsafe_path(target)
    with target.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise _unsafe_path(target)
        return stream.read()


def _posix_read_regular_file(root: Path, parts: Tuple[str, ...]) -> bytes:
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
        file_descriptor = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=descriptor)
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


def read_regular_file_at(root: Path, parts: Tuple[str, ...]) -> bytes:
    if not parts:
        raise ValueError("relative file parts are required")
    if os.name == "nt":
        return _windows_read_regular_file(root, parts)
    return _posix_read_regular_file(root, parts)


def _windows_list_directory(root: Path, parts: Tuple[str, ...]) -> Tuple[str, ...]:
    target = _windows_target(root, parts)
    metadata = target.lstat()
    if target.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise _unsafe_path(target)
    return tuple(os.listdir(str(target)))


def _posix_list_directory(root: Path, parts: Tuple[str, ...]) -> Tuple[str, ...]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    descriptors = []
    target = root.joinpath(*parts)
    try:
        descriptor = os.open(str(root), directory_flags)
        descriptors.append(descriptor)
        for part in parts:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _unsafe_path(target)
        return tuple(os.listdir(descriptor))
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


def list_directory_names_at(root: Path, parts: Tuple[str, ...]) -> Tuple[str, ...]:
    if not parts:
        raise ValueError("relative directory parts are required")
    if os.name == "nt":
        return _windows_list_directory(root, parts)
    return _posix_list_directory(root, parts)


def _lock_contention(exc: OSError) -> bool:
    return exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(
        exc, "winerror", None
    ) in (33, 36)


@contextlib.contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    ensure_private_directory(path.parent)
    descriptor = None
    locked = False
    try:
        if path.is_symlink():
            raise _unsafe_path(path)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if os.name == "nt":
            flags |= os.O_BINARY
        descriptor = os.open(str(path), flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _unsafe_path(path)
        if path.is_symlink():
            raise _unsafe_path(path)
        if os.name == "nt":
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            while True:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if not _lock_contention(exc):
                        raise
                    time.sleep(0.05)
        else:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        yield
    except DevFlowError:
        raise
    except OSError as exc:
        if descriptor is None and exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _unsafe_path(path) from exc
        message = "task lock could not be acquired" if descriptor is not None else "task lock could not be opened"
        raise DevFlowError(
            "STATE_LOCK_FAILED", message, details={"path": str(path), "error": str(exc)}
        ) from exc
    finally:
        if descriptor is not None:
            if locked:
                try:
                    if os.name == "nt":
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
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
            prefix=".{}.write.".format(path.name), suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise _unsafe_path(path)
        os.replace(str(temporary), str(path))
        temporary = None
        if os.name != "nt":
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
                temporary.unlink()
            except (FileNotFoundError, OSError):
                pass
