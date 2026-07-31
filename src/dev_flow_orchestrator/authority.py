"""Durable conversation confirmation for exact controller authority."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
from typing import Iterator, Mapping, Optional, Sequence

from .filesystem import atomic_write_bytes
from .model import DevFlowError, canonical_json_bytes, validate_task_id


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,127}$")
_DECISION = re.compile(
    r"^(同意|approve|拒绝|deny)"
    r"(?: ([A-Za-z0-9][A-Za-z0-9._@:-]{0,127}))?$"
)
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_REQUEST_SCHEMA = "dev-flow-v4-confirmation-request/v1"
_TOMBSTONE_SCHEMA = "dev-flow-v4-confirmation-tombstone/v1"
_INDEX_SCHEMA = "dev-flow-v4-confirmation-index/v1"
_EVENT_SCHEMA = "dev-flow-v4-confirmation-event/v1"
_PROJECTION_SCHEMA = "dev-flow-v4-confirmation-projection/v1"
_OBSERVATION_SCHEMA = "dev-flow-v4-confirmation-observation/v1"
_CHANNEL = "codex-user-prompt/v1"
_CURRENT_STATUSES = frozenset(("PENDING", "CONFIRMED", "DENIED"))
_STATUSES = frozenset(
    ("PENDING", "CONFIRMED", "DENIED", "CLAIMED", "CONSUMED", "STALE")
)
_COMPACTABLE_STATUSES = frozenset(("CONSUMED", "STALE"))
_MAX_BINDING_BYTES = 65536
_MAX_MAPPING_BYTES = 32768
_MAX_PROMPT_BYTES = 4096
_MAX_CWD_BYTES = 4096
_MAX_ROUTING_BYTES = 256
_MAX_INDEX_BYTES = 32 * 1024 * 1024
_MAX_PUBLIC_BYTES = 4096
_MAX_PUBLIC_REQUESTS = 8
_MAX_PUBLIC_SCOPE_BYTES = 512


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest_json(value: object) -> str:
    return _digest_bytes(canonical_json_bytes(value))


def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


class AuthorityStore:
    """Persist, decide and consume exact conversation confirmations.

    Every mutation is serialized through one data-root lock.  Callers must not
    hold a task, effect-journal or workspace lock while invoking this store.
    """

    def __init__(
        self,
        data_root: Path,
        *,
        request_limit: int = 4096,
        event_limit: int = 8192,
    ) -> None:
        self.data_root = Path(data_root)
        self.root = self.data_root / "confirmations"
        self.index_path = self.root / "index.json"
        self.lock_path = self.data_root / "locks" / "confirmation.lock"
        if (
            not isinstance(request_limit, int)
            or isinstance(request_limit, bool)
            or request_limit < 1
            or not isinstance(event_limit, int)
            or isinstance(event_limit, bool)
            or event_limit < 1
        ):
            raise DevFlowError(
                "CONFIRMATION_STORE_INVALID",
                "confirmation store limits must be positive integers",
            )
        self.request_limit = request_limit
        self.tombstone_limit = request_limit
        self.event_limit = event_limit

    @staticmethod
    def _identity(value: object, field: str) -> str:
        if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                field + " is not a portable confirmation identity",
            )
        return value

    @staticmethod
    def _routing_text(value: object, field: str, *, required: bool = True) -> str:
        if not isinstance(value, str):
            raise DevFlowError(
                "CONFIRMATION_SESSION_REQUIRED"
                if field == "session_id"
                else "CONFIRMATION_EVENT_INVALID",
                field + " must be a string",
            )
        normalized = value.strip()
        if (
            (required and not normalized)
            or len(normalized.encode("utf-8")) > _MAX_ROUTING_BYTES
        ):
            raise DevFlowError(
                "CONFIRMATION_SESSION_REQUIRED"
                if field == "session_id"
                else "CONFIRMATION_EVENT_INVALID",
                field + " is missing or exceeds the safe routing limit",
            )
        return normalized

    @staticmethod
    def _validate_json_value(value: object, field: str, depth: int = 0) -> None:
        if depth > 64:
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                field + " exceeds the safe nesting limit",
            )
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise DevFlowError(
                    "CONFIRMATION_INVALID",
                    field + " contains a non-finite number",
                )
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DevFlowError(
                        "CONFIRMATION_INVALID",
                        field + " contains a non-string object key",
                    )
                AuthorityStore._validate_json_value(item, field, depth + 1)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                AuthorityStore._validate_json_value(item, field, depth + 1)
            return
        raise DevFlowError(
            "CONFIRMATION_INVALID",
            field + " contains a non-JSON value",
        )

    @classmethod
    def _mapping(cls, value: object, field: str) -> dict:
        if not isinstance(value, Mapping):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                field + " must be an object",
            )
        cls._validate_json_value(value, field)
        try:
            encoded = canonical_json_bytes(value)
        except (RecursionError, TypeError, ValueError) as exc:
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                field + " is not canonical JSON",
            ) from exc
        if len(encoded) > _MAX_MAPPING_BYTES:
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                field + " exceeds the safe confirmation limit",
            )
        return json.loads(encoded.decode("utf-8"))

    @staticmethod
    def _local_account() -> dict:
        uid = os.getuid()
        try:
            user = pwd.getpwuid(uid).pw_name
        except (KeyError, OSError) as exc:
            raise DevFlowError(
                "CONFIRMATION_ACCOUNT_UNAVAILABLE",
                "the local execution account cannot be resolved",
            ) from exc
        if not isinstance(user, str) or not user:
            raise DevFlowError(
                "CONFIRMATION_ACCOUNT_UNAVAILABLE",
                "the local execution account cannot be resolved",
            )
        return {"uid": uid, "user": user}

    @staticmethod
    def actor_for_account(account: Mapping[str, object], role: str) -> str:
        """Derive the default audit actor from the local execution account."""

        AuthorityStore._identity(role, "actor_role")
        uid = account.get("uid")
        user_value = account.get("user")
        if (
            not isinstance(uid, int)
            or isinstance(uid, bool)
            or not isinstance(user_value, str)
            or not user_value
        ):
            raise DevFlowError(
                "CONFIRMATION_ACCOUNT_UNAVAILABLE",
                "the local execution account is invalid",
            )
        user = re.sub(r"[^A-Za-z0-9._-]+", "-", user_value)
        return "local:{}:{}".format(uid, user)

    def current_actor(self, role: str) -> dict:
        """Return the canonical actor binding for the local account and role."""

        self._identity(role, "actor_role")
        account = self._local_account()
        return {
            "id": self.actor_for_account(account, role),
            "role": role,
            "local_account": account,
        }

    @staticmethod
    def _request_id(binding: Mapping[str, object]) -> str:
        return "confirm-" + _digest_bytes(
            _REQUEST_SCHEMA.encode("utf-8")
            + b"\x00"
            + canonical_json_bytes(binding)
        )

    @staticmethod
    def _event_id(session_id: str, turn_id: str) -> str:
        return _digest_json([session_id, turn_id])

    @staticmethod
    def _store_error(
        code: str,
        message: str,
        *,
        path: Optional[Path] = None,
    ) -> DevFlowError:
        details = {} if path is None else {"path": str(path)}
        return DevFlowError(code, message, details=details)

    def _ensure_private_directory(self, path: Path) -> None:
        created = False
        try:
            info = path.lstat()
        except FileNotFoundError:
            try:
                path.mkdir(mode=0o700, parents=True, exist_ok=False)
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                raise self._store_error(
                    "CONFIRMATION_STORE_UNAVAILABLE",
                    "confirmation directory cannot be created",
                    path=path,
                ) from exc
            try:
                info = path.lstat()
            except OSError as exc:
                raise self._store_error(
                    "CONFIRMATION_STORE_UNAVAILABLE",
                    "confirmation directory cannot be inspected",
                    path=path,
                ) from exc
        if created:
            try:
                os.chmod(str(path), 0o700)
                info = path.lstat()
            except OSError as exc:
                raise self._store_error(
                    "CONFIRMATION_STORE_UNAVAILABLE",
                    "confirmation directory permissions cannot be set",
                    path=path,
                ) from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_UNSAFE",
                "confirmation directory is not private to the local account",
                path=path,
            )

    def _validate_private_file(self, path: Path) -> os.stat_result:
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise self._store_error(
                "CONFIRMATION_STORE_UNAVAILABLE",
                "confirmation file cannot be inspected",
                path=path,
            ) from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_UNSAFE",
                "confirmation file is not private to the local account",
                path=path,
            )
        return info

    @contextlib.contextmanager
    def _confirmation_lock(self) -> Iterator[None]:
        self._ensure_private_directory(self.data_root)
        self._ensure_private_directory(self.root)
        self._ensure_private_directory(self.lock_path.parent)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = None
        created = False
        try:
            try:
                descriptor = os.open(
                    str(self.lock_path),
                    os.O_RDWR | no_follow,
                )
            except FileNotFoundError:
                try:
                    descriptor = os.open(
                        str(self.lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_RDWR | no_follow,
                        0o600,
                    )
                    created = True
                except FileExistsError:
                    descriptor = os.open(
                        str(self.lock_path),
                        os.O_RDWR | no_follow,
                    )
            if created:
                os.fchmod(descriptor, 0o600)
            file_info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_info.st_mode)
                or file_info.st_uid != os.getuid()
                or stat.S_IMODE(file_info.st_mode) != 0o600
            ):
                raise self._store_error(
                    "CONFIRMATION_STORE_UNSAFE",
                    "confirmation lock is not private to the local account",
                    path=self.lock_path,
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        except DevFlowError:
            raise
        except OSError as exc:
            code = (
                "CONFIRMATION_STORE_UNSAFE"
                if exc.errno in (errno.ELOOP, errno.EPERM, errno.EACCES)
                else "CONFIRMATION_STORE_LOCK_FAILED"
            )
            raise self._store_error(
                code,
                "confirmation lock cannot be acquired",
                path=self.lock_path,
            ) from exc
        finally:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(descriptor)

    def _empty_index(self) -> dict:
        return {
            "schema": _INDEX_SCHEMA,
            "requests": {},
            "tombstones": {},
            "events": {},
        }

    def _validate_request(self, request_id: str, record: object) -> None:
        if not isinstance(record, dict):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation request record is malformed",
                path=self.index_path,
            )
        binding = record.get("binding")
        status_value = record.get("status")
        if (
            record.get("schema") != _REQUEST_SCHEMA
            or record.get("request_id") != request_id
            or not isinstance(binding, dict)
            or status_value not in _STATUSES
            or not isinstance(record.get("created_at"), str)
            or not isinstance(record.get("routing"), dict)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation request record is malformed",
                path=self.index_path,
            )
        try:
            expected_id = self._request_id(binding)
            binding_digest = _digest_json(binding)
        except (RecursionError, TypeError, ValueError) as exc:
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation request binding is malformed",
                path=self.index_path,
            ) from exc
        if (
            expected_id != request_id
            or record.get("binding_digest") != binding_digest
            or not isinstance(binding.get("task_id"), str)
            or not isinstance(binding.get("workflow_identity"), str)
            or not isinstance(binding.get("expected_revision"), int)
            or isinstance(binding.get("expected_revision"), bool)
            or not isinstance(binding.get("action_id"), str)
            or not isinstance(binding.get("grant"), str)
            or not isinstance(binding.get("actor"), dict)
            or not isinstance(binding.get("scope"), dict)
            or not isinstance(binding.get("context"), dict)
            or not isinstance(binding.get("repository_context"), dict)
            or not isinstance(binding.get("session_id"), str)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation request binding does not match its identity",
                path=self.index_path,
            )
        decision = record.get("decision")
        if status_value in ("CONFIRMED", "DENIED", "CLAIMED", "CONSUMED"):
            if (
                not isinstance(decision, dict)
                or decision.get("channel") != _CHANNEL
                or not isinstance(decision.get("session_id"), str)
                or not isinstance(decision.get("turn_id"), str)
                or not isinstance(decision.get("prompt_digest"), str)
                or not _DIGEST.fullmatch(decision["prompt_digest"])
                or not isinstance(record.get("decided_at"), str)
            ):
                raise self._store_error(
                    "CONFIRMATION_STORE_CORRUPT",
                    "confirmation decision evidence is malformed",
                    path=self.index_path,
                )
        if status_value == "CLAIMED" and not isinstance(
            record.get("claimed_at"), str
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "claimed confirmation lacks its audit timestamp",
                path=self.index_path,
            )
        if status_value == "CONSUMED" and not isinstance(
            record.get("consumed_at"), str
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "consumed confirmation lacks its audit timestamp",
                path=self.index_path,
            )
        if status_value == "STALE" and not isinstance(
            record.get("stale_at"), str
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "stale confirmation lacks its audit timestamp",
                path=self.index_path,
            )

    def _validate_tombstone(
        self,
        request_id: str,
        tombstone: object,
    ) -> None:
        if not isinstance(tombstone, dict):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation tombstone is malformed",
                path=self.index_path,
            )
        status_value = tombstone.get("status")
        binding_digest = tombstone.get("binding_digest")
        task_id = tombstone.get("task_id")
        locator = tombstone.get("locator")
        if (
            tombstone.get("schema") != _TOMBSTONE_SCHEMA
            or tombstone.get("request_id") != request_id
            or status_value not in _COMPACTABLE_STATUSES
            or not isinstance(binding_digest, str)
            or not _DIGEST.fullmatch(binding_digest)
            or not isinstance(task_id, str)
            or not isinstance(tombstone.get("terminal_at"), str)
            or not isinstance(tombstone.get("compacted_at"), str)
            or not isinstance(locator, dict)
            or locator.get("request_id") != request_id
            or locator.get("status") != status_value
            or not isinstance(locator.get("action_id"), str)
            or not isinstance(locator.get("grant"), str)
            or not isinstance(locator.get("session_id"), str)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation tombstone is malformed",
                path=self.index_path,
            )
        for field in (
            "scope_digest",
            "context_digest",
            "repository_context_digest",
        ):
            digest = locator.get(field)
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise self._store_error(
                    "CONFIRMATION_STORE_CORRUPT",
                    "confirmation tombstone locator is malformed",
                    path=self.index_path,
                )
        try:
            validate_task_id(task_id)
        except DevFlowError as exc:
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation tombstone task binding is malformed",
                path=self.index_path,
            ) from exc

    def _validate_event(self, event_id: str, event: object) -> None:
        if not isinstance(event, dict):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation event record is malformed",
                path=self.index_path,
            )
        session_id = event.get("session_id")
        turn_id = event.get("turn_id")
        prompt_digest = event.get("prompt_digest")
        if (
            event.get("schema") != _EVENT_SCHEMA
            or not isinstance(session_id, str)
            or not isinstance(turn_id, str)
            or self._event_id(session_id, turn_id) != event_id
            or not isinstance(prompt_digest, str)
            or not _DIGEST.fullmatch(prompt_digest)
            or not isinstance(event.get("observed_at"), str)
            or not isinstance(event.get("result"), dict)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation event record is malformed",
                path=self.index_path,
            )

    def _validate_index(self, index: object) -> dict:
        if (
            not isinstance(index, dict)
            or index.get("schema") != _INDEX_SCHEMA
            or not isinstance(index.get("requests"), dict)
            or not isinstance(index.get("tombstones"), dict)
            or not isinstance(index.get("events"), dict)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation index is malformed",
                path=self.index_path,
            )
        requests = index["requests"]
        tombstones = index["tombstones"]
        events = index["events"]
        if (
            len(requests) > self.request_limit
            or len(tombstones) > self.tombstone_limit
            or len(events) > self.event_limit
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation index exceeds its safe retention limit",
                path=self.index_path,
            )
        if set(requests).intersection(tombstones):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation identity exists as both request and tombstone",
                path=self.index_path,
            )
        for request_id, record in requests.items():
            if not isinstance(request_id, str):
                raise self._store_error(
                    "CONFIRMATION_STORE_CORRUPT",
                    "confirmation request identity is malformed",
                    path=self.index_path,
                )
            self._validate_request(request_id, record)
        for request_id, tombstone in tombstones.items():
            if not isinstance(request_id, str):
                raise self._store_error(
                    "CONFIRMATION_STORE_CORRUPT",
                    "confirmation tombstone identity is malformed",
                    path=self.index_path,
                )
            self._validate_tombstone(request_id, tombstone)
        for event_id, event in events.items():
            if not isinstance(event_id, str):
                raise self._store_error(
                    "CONFIRMATION_STORE_CORRUPT",
                    "confirmation event identity is malformed",
                    path=self.index_path,
                )
            self._validate_event(event_id, event)
        return index

    def _load_index(self) -> dict:
        try:
            info = self._validate_private_file(self.index_path)
        except FileNotFoundError:
            return self._empty_index()
        if info.st_size > _MAX_INDEX_BYTES:
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation index exceeds its safe byte limit",
                path=self.index_path,
            )
        try:
            payload = self.index_path.read_bytes()
            parsed = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation index cannot be decoded",
                path=self.index_path,
            ) from exc
        return self._validate_index(parsed)

    @staticmethod
    def _index_size(index: Mapping[str, object]) -> int:
        return len(canonical_json_bytes(index)) + 1

    def _tombstone_for(self, record: Mapping[str, object]) -> dict:
        status_value = record.get("status")
        binding = record.get("binding")
        request_id = record.get("request_id")
        if (
            status_value not in _COMPACTABLE_STATUSES
            or not isinstance(binding, Mapping)
            or not isinstance(request_id, str)
        ):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "only safely terminal confirmations can be compacted",
                path=self.index_path,
            )
        terminal_field = (
            "consumed_at" if status_value == "CONSUMED" else "stale_at"
        )
        terminal_at = record.get(terminal_field)
        packet = self.public_packet(record)
        return {
            "schema": _TOMBSTONE_SCHEMA,
            "request_id": request_id,
            "binding_digest": record.get("binding_digest"),
            "status": status_value,
            "task_id": binding.get("task_id"),
            "terminal_at": terminal_at,
            "compacted_at": _utc_now(),
            "locator": {
                field: packet[field]
                for field in (
                    "request_id",
                    "status",
                    "action_id",
                    "grant",
                    "session_id",
                    "scope_digest",
                    "context_digest",
                    "repository_context_digest",
                )
            },
        }

    def _compact_one_terminal(self, index: dict) -> None:
        candidates = sorted(
            request_id
            for request_id, record in index["requests"].items()
            if record.get("status") in _COMPACTABLE_STATUSES
        )
        if not candidates:
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation capacity is full with no safely compactable record",
                path=self.index_path,
            )
        if len(index["tombstones"]) >= self.tombstone_limit:
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation tombstone retention limit is full",
                path=self.index_path,
            )
        request_id = candidates[0]
        tombstone = self._tombstone_for(index["requests"][request_id])
        index["tombstones"][request_id] = tombstone
        del index["requests"][request_id]

    def _ensure_index_capacity(self, index: dict) -> None:
        while (
            len(index["requests"]) > self.request_limit
            or self._index_size(index) > _MAX_INDEX_BYTES
        ):
            self._compact_one_terminal(index)
        if len(index["tombstones"]) > self.tombstone_limit:
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation tombstone retention limit is full",
                path=self.index_path,
            )

    def _write_index(self, index: Mapping[str, object]) -> None:
        if not isinstance(index, dict):
            raise self._store_error(
                "CONFIRMATION_STORE_CORRUPT",
                "confirmation index is not mutable",
                path=self.index_path,
            )
        self._ensure_index_capacity(index)
        self._validate_index(index)
        payload = canonical_json_bytes(index) + b"\n"
        if len(payload) > _MAX_INDEX_BYTES:
            raise self._store_error(
                "CONFIRMATION_STORE_CAPACITY",
                "confirmation index exceeds its safe byte limit",
                path=self.index_path,
            )
        try:
            atomic_write_bytes(self.index_path, payload)
            self._validate_private_file(self.index_path)
        except DevFlowError as exc:
            if exc.code.startswith("CONFIRMATION_"):
                raise
            raise self._store_error(
                "CONFIRMATION_STORE_WRITE_FAILED",
                "confirmation index cannot be written atomically",
                path=self.index_path,
            ) from exc
        except OSError as exc:
            raise self._store_error(
                "CONFIRMATION_STORE_WRITE_FAILED",
                "confirmation index cannot be written atomically",
                path=self.index_path,
            ) from exc

    def _binding(
        self,
        *,
        task_id: str,
        workflow_identity: str,
        expected_revision: int,
        action_id: str,
        grant: str,
        actor_role: str,
        actor_id: Optional[str],
        scope: Optional[Mapping[str, object]],
        context: Optional[Mapping[str, object]],
        repository_context: Optional[Mapping[str, object]],
        session_id: str,
    ) -> dict:
        validate_task_id(task_id)
        workflow_value = self._routing_text(
            workflow_identity,
            "workflow_identity",
        )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "expected_revision must be a non-negative integer",
            )
        self._identity(action_id, "action_id")
        self._identity(grant, "grant")
        self._identity(actor_role, "actor_role")
        session_value = self._routing_text(session_id, "session_id")
        if repository_context is None:
            raise DevFlowError(
                "CONFIRMATION_REPOSITORY_CONTEXT_REQUIRED",
                "canonical repository context is required for confirmation",
            )
        actor = self.current_actor(actor_role)
        if actor_id is not None:
            actor["id"] = self._identity(actor_id, "actor_id")
        binding = {
            "task_id": task_id,
            "workflow_identity": workflow_value,
            "expected_revision": expected_revision,
            "action_id": action_id,
            "grant": grant,
            "actor": actor,
            "scope": self._mapping(scope or {}, "scope"),
            "context": self._mapping(context or {}, "context"),
            "repository_context": self._mapping(
                repository_context,
                "repository_context",
            ),
            "session_id": session_value,
        }
        if len(canonical_json_bytes(binding)) > _MAX_BINDING_BYTES:
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "confirmation binding exceeds the safe storage limit",
            )
        return binding

    def resolve(
        self,
        *,
        task_id: str,
        workflow_identity: str,
        expected_revision: int,
        action_id: str,
        grant: str,
        actor_role: str,
        actor_id: Optional[str] = None,
        scope: Optional[Mapping[str, object]] = None,
        context: Optional[Mapping[str, object]] = None,
        repository_context: Optional[Mapping[str, object]] = None,
        session_id: str,
        request_turn_id: Optional[str] = None,
    ) -> dict:
        """Create or reload the request for one exact canonical binding."""

        binding = self._binding(
            task_id=task_id,
            workflow_identity=workflow_identity,
            expected_revision=expected_revision,
            action_id=action_id,
            grant=grant,
            actor_role=actor_role,
            actor_id=actor_id,
            scope=scope,
            context=context,
            repository_context=repository_context,
            session_id=session_id,
        )
        turn_value = (
            None
            if request_turn_id is None
            else self._routing_text(
                request_turn_id,
                "request_turn_id",
            )
        )
        request_id = self._request_id(binding)
        binding_digest = _digest_json(binding)
        with self._confirmation_lock():
            index = self._load_index()
            existing = index["requests"].get(request_id)
            if existing is not None:
                if existing.get("binding") != binding:
                    raise DevFlowError(
                        "CONFIRMATION_BINDING_MISMATCH",
                        "stored confirmation does not match the exact request",
                        details={"request_id": request_id},
                    )
                return copy.deepcopy(existing)
            tombstone = index["tombstones"].get(request_id)
            if tombstone is not None:
                if tombstone.get("binding_digest") != binding_digest:
                    raise DevFlowError(
                        "CONFIRMATION_BINDING_MISMATCH",
                        "stored tombstone does not match the exact request",
                        details={"request_id": request_id},
                    )
                return copy.deepcopy(tombstone)
            record = {
                "schema": _REQUEST_SCHEMA,
                "request_id": request_id,
                "binding_digest": binding_digest,
                "binding": binding,
                "status": "PENDING",
                "created_at": _utc_now(),
                "routing": {
                    "request_turn_id": turn_value,
                },
                "decided_at": None,
                "decision": None,
                "claimed_at": None,
                "consumed_at": None,
                "stale_at": None,
            }
            index["requests"][request_id] = record
            self._write_index(index)
            return copy.deepcopy(record)

    @staticmethod
    def _bounded_scope(scope: Mapping[str, object]) -> object:
        encoded = canonical_json_bytes(scope)
        if len(encoded) <= _MAX_PUBLIC_SCOPE_BYTES:
            return copy.deepcopy(dict(scope))
        return {
            "omitted": True,
            "digest": _digest_bytes(encoded),
        }

    @classmethod
    def public_packet(cls, record: Mapping[str, object]) -> dict:
        """Return the bounded model-visible locator for one private record."""

        if record.get("schema") == _TOMBSTONE_SCHEMA:
            locator = record.get("locator")
            if not isinstance(locator, Mapping):
                raise DevFlowError(
                    "CONFIRMATION_INVALID",
                    "confirmation tombstone cannot be projected",
                )
            return copy.deepcopy(dict(locator))
        binding = record.get("binding")
        request_id = record.get("request_id")
        if not isinstance(binding, Mapping) or not isinstance(request_id, str):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "confirmation record cannot be projected",
            )
        scope = binding.get("scope")
        context = binding.get("context")
        repository_context = binding.get("repository_context")
        if (
            not isinstance(scope, Mapping)
            or not isinstance(context, Mapping)
            or not isinstance(repository_context, Mapping)
        ):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "confirmation record cannot be projected",
            )
        return {
            "request_id": request_id,
            "status": record.get("status"),
            "action_id": binding.get("action_id"),
            "grant": binding.get("grant"),
            "session_id": binding.get("session_id"),
            "scope": cls._bounded_scope(scope),
            "scope_digest": _digest_json(scope),
            "context_digest": _digest_json(context),
            "repository_context_digest": _digest_json(repository_context),
            "reply_forms": {
                "approve": [
                    "同意 " + request_id,
                    "approve " + request_id,
                ],
                "deny": [
                    "拒绝 " + request_id,
                    "deny " + request_id,
                ],
                "bare_requires_unique": True,
            },
        }

    def projection(
        self,
        *,
        task_id: str,
        workflow_identity: str,
        expected_revision: int,
        action_id: Optional[str] = None,
        action_ids: Optional[Sequence[str]] = None,
        session_id: str,
        repository_context: Mapping[str, object],
    ) -> dict:
        """Project only current request locators for one routed action."""

        validate_task_id(task_id)
        workflow_value = self._routing_text(
            workflow_identity,
            "workflow_identity",
        )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "expected_revision must be a non-negative integer",
            )
        if (action_id is None) == (action_ids is None):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "exactly one action selector is required for projection",
            )
        if action_id is not None:
            action_values = [self._identity(action_id, "action_id")]
        else:
            if (
                isinstance(action_ids, (str, bytes))
                or not isinstance(action_ids, Sequence)
            ):
                raise DevFlowError(
                    "CONFIRMATION_INVALID",
                    "action_ids must be a bounded identity list",
                )
            action_values = sorted(
                {
                    self._identity(item, "action_id")
                    for item in action_ids
                }
            )
            if not action_values or len(action_values) > 256:
                raise DevFlowError(
                    "CONFIRMATION_INVALID",
                    "action_ids must contain 1-256 identities",
                )
        action_set = frozenset(action_values)
        session_value = self._routing_text(session_id, "session_id")
        repository_value = self._mapping(
            repository_context,
            "repository_context",
        )
        with self._confirmation_lock():
            index = self._load_index()
            records = []
            for request_id in sorted(index["requests"]):
                record = index["requests"][request_id]
                binding = record["binding"]
                if (
                    record["status"] in _CURRENT_STATUSES
                    and binding["task_id"] == task_id
                    and binding["workflow_identity"] == workflow_value
                    and binding["expected_revision"] == expected_revision
                    and binding["action_id"] in action_set
                    and binding["session_id"] == session_value
                    and binding["repository_context"] == repository_value
                ):
                    records.append(record)
            statuses = sorted({record["status"] for record in records})
            aggregate = (
                "NONE"
                if not statuses
                else statuses[0]
                if len(statuses) == 1
                else "MIXED"
            )
            result = {
                "schema": _PROJECTION_SCHEMA,
                "status": aggregate,
                "requests": [],
                "overflow_count": len(records),
            }
            for record in records[:_MAX_PUBLIC_REQUESTS]:
                packet = self.public_packet(record)
                trial = dict(result)
                trial["requests"] = result["requests"] + [packet]
                trial["overflow_count"] = len(records) - len(trial["requests"])
                if len(canonical_json_bytes(trial)) > _MAX_PUBLIC_BYTES:
                    break
                result = trial
            result["overflow_count"] = len(records) - len(result["requests"])
            return result

    def records_for_task(self, task_id: str) -> tuple:
        """Return a bounded private snapshot for controller reconciliation."""

        validate_task_id(task_id)
        with self._confirmation_lock():
            index = self._load_index()
            return tuple(
                copy.deepcopy(index["requests"][request_id])
                for request_id in sorted(index["requests"])
                if index["requests"][request_id]["binding"]["task_id"]
                == task_id
            )

    def evidence_for_task(self, task_id: str) -> tuple:
        """Return full records plus terminal tombstones as private evidence.

        Tombstones in this snapshot are historical proof only.  Live
        confirmation resolution, projection and lifecycle transitions continue
        to use the full-request index and never treat this evidence view as
        authority.
        """

        validate_task_id(task_id)
        with self._confirmation_lock():
            index = self._load_index()
            evidence = [
                copy.deepcopy(index["requests"][request_id])
                for request_id in sorted(index["requests"])
                if index["requests"][request_id]["binding"]["task_id"]
                == task_id
            ]
            evidence.extend(
                copy.deepcopy(index["tombstones"][request_id])
                for request_id in sorted(index["tombstones"])
                if index["tombstones"][request_id]["task_id"] == task_id
            )
            return tuple(
                sorted(
                    evidence,
                    key=lambda record: record["request_id"].encode("utf-8"),
                )
            )

    @staticmethod
    def _observation(
        status_value: str,
        *,
        request_id: Optional[str] = None,
        request_ids=None,
        eligible_count: int = 0,
        code: Optional[str] = None,
    ) -> dict:
        result = {
            "schema": _OBSERVATION_SCHEMA,
            "status": status_value,
            "request_id": request_id,
            "request_ids": list(request_ids or []),
            "eligible_count": eligible_count,
        }
        if code is not None:
            result["code"] = code
        return result

    def observe_user_prompt(
        self,
        *,
        session_id: str,
        turn_id: str,
        cwd: str,
        prompt: str,
        eligible_task_ids: Sequence[str],
    ) -> dict:
        """Observe one bounded UserPromptSubmit event without applying work."""

        session_value = self._routing_text(session_id, "session_id")
        turn_value = self._routing_text(turn_id, "turn_id")
        if (
            not isinstance(cwd, str)
            or not cwd.strip()
            or len(cwd.encode("utf-8")) > _MAX_CWD_BYTES
        ):
            raise DevFlowError(
                "CONFIRMATION_EVENT_INVALID",
                "cwd is missing or exceeds the safe event limit",
            )
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES
        ):
            raise DevFlowError(
                "CONFIRMATION_EVENT_INVALID",
                "prompt is missing or exceeds the safe event limit",
            )
        if (
            isinstance(eligible_task_ids, (str, bytes))
            or not isinstance(eligible_task_ids, Sequence)
        ):
            raise DevFlowError(
                "CONFIRMATION_EVENT_INVALID",
                "eligible_task_ids must be a bounded task list",
            )
        eligible_values = []
        for task_id in eligible_task_ids:
            eligible_values.append(validate_task_id(task_id))
        eligible_values = sorted(set(eligible_values))
        if len(eligible_values) > 256:
            raise DevFlowError(
                "CONFIRMATION_EVENT_INVALID",
                "eligible_task_ids exceeds the safe event limit",
            )
        eligible_set = frozenset(eligible_values)
        prompt_digest = _digest_bytes(prompt.encode("utf-8"))
        event_id = self._event_id(session_value, turn_value)
        with self._confirmation_lock():
            index = self._load_index()
            existing_event = index["events"].get(event_id)
            if existing_event is not None:
                if existing_event["prompt_digest"] == prompt_digest:
                    return copy.deepcopy(existing_event["result"])
                return self._observation(
                    "CONFLICT",
                    code="CONFIRMATION_EVENT_CONFLICT",
                )
            if len(index["events"]) >= self.event_limit:
                raise self._store_error(
                    "CONFIRMATION_STORE_CAPACITY",
                    "confirmation event retention limit is full",
                    path=self.index_path,
                )
            candidates = []
            for request_id in sorted(index["requests"]):
                record = index["requests"][request_id]
                binding = record["binding"]
                if (
                    record["status"] == "PENDING"
                    and binding["session_id"] == session_value
                    and binding["task_id"] in eligible_set
                ):
                    candidates.append(record)

            match = _DECISION.fullmatch(prompt.strip())
            selected = None
            decision_status = None
            result = None
            if match is None:
                result = self._observation("IGNORED")
            else:
                verb, named_request_id = match.groups()
                decision_status = (
                    "CONFIRMED" if verb in ("同意", "approve") else "DENIED"
                )
                if named_request_id is not None:
                    for candidate in candidates:
                        if candidate["request_id"] == named_request_id:
                            selected = candidate
                            break
                    if selected is None:
                        result = self._observation(
                            "NO_MATCH",
                            request_id=named_request_id,
                            eligible_count=len(candidates),
                        )
                elif len(candidates) == 1:
                    selected = candidates[0]
                elif not candidates:
                    result = self._observation("NO_MATCH")
                else:
                    ids = [
                        candidate["request_id"]
                        for candidate in candidates[:_MAX_PUBLIC_REQUESTS]
                    ]
                    result = self._observation(
                        "AMBIGUOUS",
                        request_ids=ids,
                        eligible_count=len(candidates),
                    )
            observed_at = _utc_now()
            if selected is not None:
                selected["status"] = decision_status
                selected["decided_at"] = observed_at
                selected["decision"] = {
                    "channel": _CHANNEL,
                    "session_id": session_value,
                    "turn_id": turn_value,
                    "prompt_digest": prompt_digest,
                    "cwd_digest": _digest_bytes(cwd.encode("utf-8")),
                    "eligible_task_ids_digest": _digest_json(eligible_values),
                }
                result = self._observation(
                    decision_status,
                    request_id=selected["request_id"],
                    eligible_count=len(candidates),
                )
            event = {
                "schema": _EVENT_SCHEMA,
                "session_id": session_value,
                "turn_id": turn_value,
                "prompt_digest": prompt_digest,
                "cwd_digest": _digest_bytes(cwd.encode("utf-8")),
                "eligible_task_ids_digest": _digest_json(eligible_values),
                "observed_at": observed_at,
                "result": result,
            }
            index["events"][event_id] = event
            self._write_index(index)
            return copy.deepcopy(result)

    def _transition(
        self,
        task_id: str,
        request_id: str,
        *,
        target: str,
    ) -> dict:
        validate_task_id(task_id)
        self._identity(request_id, "request_id")
        if target not in ("CLAIMED", "CONSUMED", "STALE"):
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "confirmation lifecycle target is invalid",
            )
        with self._confirmation_lock():
            index = self._load_index()
            record = index["requests"].get(request_id)
            if record is None:
                tombstone = index["tombstones"].get(request_id)
                if tombstone is not None:
                    if tombstone.get("task_id") != task_id:
                        raise DevFlowError(
                            "CONFIRMATION_BINDING_MISMATCH",
                            "confirmation tombstone belongs to another task",
                            details={"request_id": request_id},
                        )
                    current = tombstone["status"]
                    if current == target:
                        return copy.deepcopy(tombstone)
                    if current == "CONSUMED":
                        raise DevFlowError(
                            "CONFIRMATION_CONSUMED",
                            "confirmation request was already consumed",
                            details={"request_id": request_id},
                        )
                    raise DevFlowError(
                        "CONFIRMATION_STALE",
                        "confirmation request is stale",
                        details={"request_id": request_id},
                    )
                raise DevFlowError(
                    "CONFIRMATION_INVALID",
                    "confirmation request does not exist",
                    details={"request_id": request_id},
                )
            if record["binding"]["task_id"] != task_id:
                raise DevFlowError(
                    "CONFIRMATION_BINDING_MISMATCH",
                    "confirmation request belongs to another task",
                    details={"request_id": request_id},
                )
            current = record["status"]
            if current == target and target in (
                "CLAIMED",
                "CONSUMED",
                "STALE",
            ):
                return copy.deepcopy(record)
            if current == "PENDING":
                if target != "STALE":
                    raise DevFlowError(
                        "CONFIRMATION_PENDING",
                        "confirmation request has not been decided",
                        details={"request_id": request_id},
                    )
            elif current == "CONFIRMED":
                pass
            elif current == "DENIED":
                raise DevFlowError(
                    "CONFIRMATION_DENIED",
                    "confirmation denial is terminal for this exact binding",
                    details={"request_id": request_id},
                )
            elif current == "CLAIMED":
                if target != "CONSUMED":
                    raise DevFlowError(
                        "CONFIRMATION_CLAIMED",
                        "confirmation is already bound to an effect claim",
                        details={"request_id": request_id},
                    )
            elif current == "CONSUMED":
                raise DevFlowError(
                    "CONFIRMATION_CONSUMED",
                    "confirmation request was already consumed",
                    details={"request_id": request_id},
                )
            elif current == "STALE":
                raise DevFlowError(
                    "CONFIRMATION_STALE",
                    "confirmation request is stale",
                    details={"request_id": request_id},
                )
            allowed = (
                (current == "CONFIRMED" and target in ("CLAIMED", "CONSUMED", "STALE"))
                or (current == "CLAIMED" and target == "CONSUMED")
                or (current == "PENDING" and target == "STALE")
            )
            if not allowed:
                raise DevFlowError(
                    "CONFIRMATION_LIFECYCLE_CONFLICT",
                    "confirmation lifecycle transition is not allowed",
                    details={
                        "request_id": request_id,
                        "status": current,
                        "target": target,
                    },
                )
            timestamp_field = {
                "CLAIMED": "claimed_at",
                "CONSUMED": "consumed_at",
                "STALE": "stale_at",
            }[target]
            record["status"] = target
            record[timestamp_field] = _utc_now()
            self._write_index(index)
            return copy.deepcopy(record)

    def mark_claimed(self, task_id: str, request_id: str) -> dict:
        """Bind a confirmed request to an already durable effect claim."""

        return self._transition(task_id, request_id, target="CLAIMED")

    def consume(self, task_id: str, request_id: str) -> dict:
        """Consume confirmed authority after its durable success boundary."""

        return self._transition(task_id, request_id, target="CONSUMED")

    def mark_stale(self, task_id: str, request_id: str) -> dict:
        """Retire a pending/confirmed request after exact binding drift."""

        return self._transition(task_id, request_id, target="STALE")
