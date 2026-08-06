"""Compatibility façade for private controller-storage primitives."""

from ._platform.storage import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
    list_directory_names_at,
    read_regular_file_at,
)

__all__ = (
    "atomic_write_bytes",
    "ensure_private_directory",
    "exclusive_file_lock",
    "list_directory_names_at",
    "read_regular_file_at",
)
