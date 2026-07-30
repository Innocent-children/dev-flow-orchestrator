from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import release_ledger


ROOT = Path(__file__).resolve().parents[1]
FIRST_INTRODUCTION_PATH = (
    ROOT
    / "workflows"
    / "release-provenance"
    / "first-introduction.json"
)
RESERVED_V3_LEDGER_PATH = ROOT / "workflows" / "release-ledger.json"
RESERVED_V3_ACTIVATION_PATH = (
    ROOT
    / "workflows"
    / "release-provenance"
    / "reserved-v3-activation.json"
)


def reserved_v3_ledger_bytes() -> bytes:
    current = json.loads(RESERVED_V3_LEDGER_PATH.read_bytes())
    return release_ledger.canonical_json_bytes(
        {
            "schema": current["schema"],
            "reservations": current["reservations"][
                : release_ledger.RESERVED_V3_RESERVATION_COUNT
            ],
        }
    )


def package_ledger_bytes() -> bytes:
    return release_ledger.append_release_reservations(
        release_ledger.empty_release_ledger_bytes(),
        release_ledger.package_release_reservations(ROOT),
    )


def first_introduction_input(
) -> release_ledger.FirstIntroductionProvenanceInput:
    return release_ledger.FirstIntroductionProvenanceInput(
        manifest_bytes=release_ledger.build_first_introduction_bytes(
            repository=ROOT,
            plugin_root=ROOT,
        ),
        repository=ROOT,
        plugin_root=ROOT,
    )


def release_review_bytes(
    *,
    provenance_sha256: str,
    candidate_sha256: str,
) -> bytes:
    return release_ledger.canonical_json_bytes(
        {
            "schema": release_ledger.RELEASE_REVIEW_SCHEMA,
            "reviewer_id": "independent-reviewer",
            "provenance_sha256": provenance_sha256,
            "base_commit": (
                release_ledger.FIRST_INTRODUCTION_BASE_COMMIT
            ),
            "base_tree": release_ledger.FIRST_INTRODUCTION_BASE_TREE,
            "inventory_sha256": (
                release_ledger.FIRST_INTRODUCTION_INVENTORY_SHA256
            ),
            "candidate_sha256": candidate_sha256,
        }
    )


def synthetic_handler(
    name: str,
    *,
    version: int,
) -> tuple[dict[str, object], dict[str, object]]:
    identity = {
        "registry": "commands",
        "id": f"command.{name}/v{version}",
        "version": f"v{version}",
        "contract_id": "dev-flow-command/v1",
    }
    reservation = {
        **identity,
        "implementation_sha256": hashlib.sha256(
            f"implementation:{name}:{version}".encode("utf-8")
        ).hexdigest(),
    }
    return identity, reservation


def synthetic_reservation(
    workflow_id: str,
    workflow_version: int,
    handler: dict[str, object],
) -> dict[str, object]:
    material = f"{workflow_id}:{workflow_version}".encode("utf-8")
    return {
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "graph_sha256": hashlib.sha256(
            b"graph:" + material
        ).hexdigest(),
        "bundle_sha256": hashlib.sha256(
            b"bundle:" + material
        ).hexdigest(),
        "handlers": [handler],
    }


@contextmanager
def synthetic_package(
    workflows: list[dict[str, object]],
    handlers: list[dict[str, object]],
    reservations: list[dict[str, object]],
):
    introduction = json.loads(FIRST_INTRODUCTION_PATH.read_bytes())
    historical_workflows = tuple(
        introduction["introduced_workflows"]
    )
    historical_handlers = tuple(
        introduction["introduced_handlers"]
    )
    historical_reservations = list(
        json.loads(reserved_v3_ledger_bytes())["reservations"]
    )
    package_workflows = sorted(
        [*historical_workflows, *workflows],
        key=release_ledger._workflow_sort_key,
    )
    package_handlers = sorted(
        [*historical_handlers, *handlers],
        key=release_ledger._handler_sort_key,
    )
    with mock.patch.object(
        release_ledger,
        "discover_introduced_identity_keys",
        return_value=(
            tuple(package_workflows),
            tuple(package_handlers),
        ),
    ), mock.patch.object(
        release_ledger,
        "package_release_reservations",
        return_value=tuple(
            [*historical_reservations, *reservations]
        ),
    ):
        yield


def build_reserved_epoch_fixture(
    workflow_id: str = "zeta",
    workflow_version: int = 4,
) -> tuple[
    bytes,
    bytes,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    handler_identity, handler_reservation = synthetic_handler(
        workflow_id,
        version=workflow_version,
    )
    reservation = synthetic_reservation(
        workflow_id,
        workflow_version,
        handler_reservation,
    )
    result_ledger = release_ledger.append_release_reservations(
        reserved_v3_ledger_bytes(),
        (reservation,),
    )
    workflow = {
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
    }
    with synthetic_package(
        [workflow],
        [handler_identity],
        [reservation],
    ):
        epoch = release_ledger.build_introduction_epoch_bytes(
            epoch_id="introduction-epoch-1",
            epoch_sequence=1,
            predecessor_first_introduction_bytes=(
                FIRST_INTRODUCTION_PATH.read_bytes()
            ),
            predecessor_ledger_bytes=(
                reserved_v3_ledger_bytes()
            ),
            predecessor_activation_bytes=(
                RESERVED_V3_ACTIVATION_PATH.read_bytes()
            ),
            current_ledger_bytes=result_ledger,
            repository=ROOT,
            plugin_root=ROOT,
        )
    return (
        epoch,
        result_ledger,
        workflow,
        handler_identity,
        reservation,
    )


class ReleaseLedgerTests(unittest.TestCase):
    def test_exact_first_introduction_git_inventory_vector(self) -> None:
        evidence = (
            release_ledger.observe_first_introduction_git_inventory(
                ROOT
            )
        )

        self.assertEqual(evidence.object_format, "sha1")
        self.assertEqual(
            evidence.base_commit,
            "2dc397411ad1ea5f2a43d43e881523b125bb5eec",
        )
        self.assertEqual(
            evidence.base_tree,
            "ee7de366a818d8800b4808015f2d8ae4c4405136",
        )
        self.assertEqual(evidence.raw_size, 7912)
        self.assertEqual(
            evidence.inventory_sha256,
            "43bf5e1da67a18e6beb15c7915357e7f84975c369d7ed165f50c84f40ba2b886",
        )
        self.assertFalse(
            any(path.startswith("workflows/") for path in evidence.paths)
        )

    def test_first_introduction_manifest_binds_exact_package_keys(
        self,
    ) -> None:
        source = release_ledger.build_first_introduction_bytes(
            repository=ROOT,
            plugin_root=ROOT,
        )
        manifest, digest = (
            release_ledger.validate_first_introduction_bytes(
                source,
                repository=ROOT,
                plugin_root=ROOT,
            )
        )
        expected_workflows, expected_handlers = (
            release_ledger.discover_introduced_identity_keys(ROOT)
        )

        self.assertEqual(
            manifest["introduced_workflows"],
            list(expected_workflows),
        )
        self.assertEqual(
            manifest["introduced_handlers"],
            list(expected_handlers),
        )
        self.assertEqual(digest, hashlib.sha256(source).hexdigest())
        self.assertEqual(
            release_ledger.canonical_json_bytes(manifest), source
        )

    def test_first_introduction_rejects_mutable_or_unknown_bindings(
        self,
    ) -> None:
        source = release_ledger.build_first_introduction_bytes(
            repository=ROOT,
            plugin_root=ROOT,
        )
        original = json.loads(source)
        cases = {
            "object-format": {
                **original,
                "git_object_format": "sha256",
            },
            "commit": {**original, "base_commit": "0" * 40},
            "tree": {**original, "base_tree": "0" * 40},
            "inventory": {
                **original,
                "inventory_sha256": "0" * 64,
            },
            "change": {**original, "change_id": "other-change"},
            "workflow-set": {
                **original,
                "introduced_workflows": original[
                    "introduced_workflows"
                ][1:],
            },
            "handler-set": {
                **original,
                "introduced_handlers": original[
                    "introduced_handlers"
                ][1:],
            },
            "self-digest": {**original, "sha256": "0" * 64},
            "candidate-digest": {
                **original,
                "candidate_sha256": "0" * 64,
            },
            "review-digest": {
                **original,
                "review_sha256": "0" * 64,
            },
            "handoff-digest": {
                **original,
                "handoff_sha256": "0" * 64,
            },
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ):
                    release_ledger.validate_first_introduction_bytes(
                        release_ledger.canonical_json_bytes(candidate),
                        repository=ROOT,
                        plugin_root=ROOT,
                    )

    def test_first_introduction_rejects_preexisting_workflow_path(
        self,
    ) -> None:
        original_run_git = release_ledger._run_git
        raw = original_run_git(
            ROOT,
            [
                "ls-tree",
                "-rz",
                "--full-tree",
                release_ledger.FIRST_INTRODUCTION_BASE_COMMIT,
            ],
        )
        injected = (
            raw
            + (
                b"100644 blob "
                + (b"0" * 40)
                + b"\tworkflows/catalog.json\0"
            )
        )
        injected_digest = (
            release_ledger.first_introduction_inventory_sha256(
                injected
            )
        )

        def fake_run_git(
            repository: Path, arguments: object
        ) -> bytes:
            if list(arguments)[:2] == ["ls-tree", "-rz"]:
                return injected
            return original_run_git(repository, arguments)

        with mock.patch.object(
            release_ledger, "_run_git", side_effect=fake_run_git
        ), mock.patch.object(
            release_ledger,
            "FIRST_INTRODUCTION_RAW_INVENTORY_BYTES",
            len(injected),
        ), mock.patch.object(
            release_ledger,
            "FIRST_INTRODUCTION_INVENTORY_SHA256",
            injected_digest,
        ):
            with self.assertRaises(
                release_ledger.ReleaseLedgerError
            ) as raised:
                release_ledger.observe_first_introduction_git_inventory(
                    ROOT
                )
        self.assertEqual(
            raised.exception.code,
            "FIRST_INTRODUCTION_IDENTITY_PREEXISTED",
        )

    def test_release_ledger_is_strict_canonical_and_append_only(
        self,
    ) -> None:
        reservations = (
            release_ledger.package_release_reservations(ROOT)
        )
        empty = release_ledger.empty_release_ledger_bytes()
        first = release_ledger.append_release_reservations(
            empty, reservations[:1]
        )
        complete = release_ledger.append_release_reservations(
            first, reservations[1:]
        )

        validated = release_ledger.validate_release_ledger_bytes(
            complete, previous_ledger_bytes=first
        )
        self.assertEqual(
            validated["reservations"], list(reservations)
        )
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.validate_release_ledger_bytes(
                json.dumps(validated, indent=2).encode("utf-8")
            )
        self.assertEqual(
            raised.exception.code, "RELEASE_JSON_NONCANONICAL"
        )

        changed = json.loads(complete)
        changed["reservations"][0]["bundle_sha256"] = "0" * 64
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.validate_release_ledger_bytes(
                release_ledger.canonical_json_bytes(changed),
                previous_ledger_bytes=first,
            )
        self.assertEqual(
            raised.exception.code, "RELEASE_LEDGER_HISTORY_MUTATED"
        )

        deleted = json.loads(complete)
        del deleted["reservations"][0]
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.validate_release_ledger_bytes(
                release_ledger.canonical_json_bytes(deleted),
                previous_ledger_bytes=complete,
            )
        self.assertEqual(
            raised.exception.code, "RELEASE_LEDGER_HISTORY_MUTATED"
        )

    def test_package_reservations_bind_graph_bundle_and_handlers(
        self,
    ) -> None:
        ledger = package_ledger_bytes()
        validated = release_ledger.validate_ledger_against_package(
            ledger, plugin_root=ROOT
        )

        self.assertEqual(len(validated["reservations"]), 6)
        self.assertEqual(
            {
                (
                    reservation["workflow_id"],
                    reservation["workflow_version"],
                )
                for reservation in validated["reservations"]
            },
            {
                ("full", 3),
                ("full", 4),
                ("full-legacy", 2),
                ("lite", 3),
                ("lite", 4),
                ("lite-legacy", 2),
            },
        )
        self.assertTrue(
            all(
                reservation["handlers"]
                for reservation in validated["reservations"]
            )
        )
        substituted = json.loads(ledger)
        substituted["reservations"][0]["handlers"][0][
            "implementation_sha256"
        ] = "0" * 64
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.validate_ledger_against_package(
                release_ledger.canonical_json_bytes(substituted),
                plugin_root=ROOT,
            )
        self.assertEqual(
            raised.exception.code,
            "RELEASE_RESERVED_IDENTITY_UNRESOLVABLE",
        )

    def test_data_root_scans_are_negative_blockers_not_absence_proof(
        self,
    ) -> None:
        reservation = next(
            item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
        )
        empty_ledger = release_ledger.empty_release_ledger_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            (data_root / "tasks").mkdir()
            no_provenance = (
                release_ledger.evaluate_unreleased_regeneration(
                    workflow_id="full",
                    workflow_version=3,
                    bundle_sha256=str(
                        reservation["bundle_sha256"]
                    ),
                    ledger_bytes=empty_ledger,
                    activation_profiles=(),
                    data_roots=(data_root,),
                )
            )
            omitted = (
                release_ledger.evaluate_unreleased_regeneration(
                    workflow_id="full",
                    workflow_version=3,
                    bundle_sha256=str(
                        reservation["bundle_sha256"]
                    ),
                    ledger_bytes=empty_ledger,
                    activation_profiles=(),
                )
            )
            proven = (
                release_ledger.evaluate_unreleased_regeneration(
                    workflow_id="full",
                    workflow_version=3,
                    bundle_sha256=str(
                        reservation["bundle_sha256"]
                    ),
                    ledger_bytes=empty_ledger,
                    activation_profiles=(),
                    first_introduction=first_introduction_input(),
                    data_roots=(data_root,),
                )
            )

            self.assertFalse(no_provenance.allowed)
            self.assertFalse(omitted.allowed)
            self.assertIn(
                "RELEASE_AUTHORITATIVE_PROVENANCE_MISSING",
                no_provenance.blocker_codes,
            )
            self.assertFalse(
                no_provenance.data_root_scan_is_authoritative_absence_proof
            )
            self.assertFalse(
                omitted.data_root_scan_is_authoritative_absence_proof
            )
            self.assertTrue(proven.allowed)
            self.assertFalse(
                proven.data_root_scan_is_authoritative_absence_proof
            )

            task_dir = data_root / "tasks" / "task-a"
            task_dir.mkdir()
            (task_dir / "state.json").write_text(
                json.dumps(
                    {
                        "task_id": "task-a",
                        "workflow_ref": {
                            "id": "full",
                            "version": 3,
                            "bundle_sha256": reservation[
                                "bundle_sha256"
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            pinned = (
                release_ledger.evaluate_unreleased_regeneration(
                    workflow_id="full",
                    workflow_version=3,
                    bundle_sha256=str(
                        reservation["bundle_sha256"]
                    ),
                    ledger_bytes=empty_ledger,
                    activation_profiles=(),
                    first_introduction=first_introduction_input(),
                    data_roots=(data_root,),
                )
            )
            self.assertFalse(pinned.allowed)
            self.assertIn(
                "RELEASE_UNRESERVED_TASK_REFERENCE",
                pinned.blocker_codes,
            )

    def test_regeneration_requires_validated_provenance_bytes(
        self,
    ) -> None:
        reservation = next(
            item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
        )
        arguments = {
            "workflow_id": "full",
            "workflow_version": 3,
            "bundle_sha256": str(reservation["bundle_sha256"]),
            "ledger_bytes": (
                release_ledger.empty_release_ledger_bytes()
            ),
            "activation_profiles": (),
        }
        with self.assertRaises(TypeError):
            release_ledger.evaluate_unreleased_regeneration(
                **arguments,
                immutable_first_introduction_valid=True,
            )
        forged = release_ledger.FirstIntroductionProvenanceInput(
            manifest_bytes=release_ledger.canonical_json_bytes(
                {
                    "schema": (
                        release_ledger.FIRST_INTRODUCTION_SCHEMA
                    )
                }
            ),
            repository=ROOT,
            plugin_root=ROOT,
        )
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ):
            release_ledger.evaluate_unreleased_regeneration(
                **arguments,
                first_introduction=forged,
            )

    def test_activation_exposure_and_reservation_boundaries_fail_closed(
        self,
    ) -> None:
        reservation = next(
            item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
        )
        empty = release_ledger.empty_release_ledger_bytes()
        active = {
            "workflow_id": "full",
            "workflow_version": 3,
            "bundle_sha256": reservation["bundle_sha256"],
            "active": True,
        }

        active_decision = (
            release_ledger.evaluate_unreleased_regeneration(
                workflow_id="full",
                workflow_version=3,
                bundle_sha256=str(reservation["bundle_sha256"]),
                ledger_bytes=empty,
                activation_profiles=(active,),
                first_introduction=first_introduction_input(),
            )
        )
        exposed = release_ledger.evaluate_unreleased_regeneration(
            workflow_id="full",
            workflow_version=3,
            bundle_sha256=str(reservation["bundle_sha256"]),
            ledger_bytes=empty,
            activation_profiles=(),
            first_introduction=first_introduction_input(),
            exposure_kinds=("installation",),
        )
        self.assertIn(
            "RELEASE_PROFILE_PIN_ELIGIBLE",
            active_decision.blocker_codes,
        )
        self.assertIn(
            "RELEASE_IDENTITY_EXPOSED", exposed.blocker_codes
        )

        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.require_exact_reservation_before_exposure(
                workflow_id="full",
                workflow_version=3,
                expected_reservation=reservation,
                ledger_bytes=empty,
            )
        self.assertEqual(
            raised.exception.code, "RELEASE_RESERVATION_REQUIRED"
        )
        reserved = release_ledger.append_release_reservations(
            empty, (reservation,)
        )
        release_ledger.require_exact_reservation_before_exposure(
            workflow_id="full",
            workflow_version=3,
            expected_reservation=reservation,
            ledger_bytes=reserved,
        )
        after_boundary = (
            release_ledger.evaluate_unreleased_regeneration(
                workflow_id="full",
                workflow_version=3,
                bundle_sha256=str(reservation["bundle_sha256"]),
                ledger_bytes=reserved,
                activation_profiles=(),
                first_introduction=first_introduction_input(),
            )
        )
        self.assertFalse(after_boundary.allowed)
        self.assertIn(
            "RELEASE_IDENTITY_RESERVED",
            after_boundary.blocker_codes,
        )

    def test_release_review_binds_provenance_and_candidate(self) -> None:
        provenance = release_ledger.build_first_introduction_bytes(
            repository=ROOT,
            plugin_root=ROOT,
        )
        provenance_sha256 = hashlib.sha256(provenance).hexdigest()
        candidate_sha256 = "c" * 64
        review = {
            "schema": "dev-flow-release-review/v1",
            "reviewer_id": "independent-reviewer",
            "provenance_sha256": provenance_sha256,
            "base_commit": (
                release_ledger.FIRST_INTRODUCTION_BASE_COMMIT
            ),
            "base_tree": release_ledger.FIRST_INTRODUCTION_BASE_TREE,
            "inventory_sha256": (
                release_ledger.FIRST_INTRODUCTION_INVENTORY_SHA256
            ),
            "candidate_sha256": candidate_sha256,
        }
        encoded = release_ledger.canonical_json_bytes(review)

        validated = release_ledger.validate_release_review_bytes(
            encoded,
            provenance_sha256=provenance_sha256,
            candidate_sha256=candidate_sha256,
        )
        self.assertEqual(
            validated["reviewer_id"], "independent-reviewer"
        )
        for field in (
            "provenance_sha256",
            "base_commit",
            "base_tree",
            "inventory_sha256",
            "candidate_sha256",
        ):
            with self.subTest(field=field):
                changed = {**review, field: "0" * len(str(review[field]))}
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ):
                    release_ledger.validate_release_review_bytes(
                        release_ledger.canonical_json_bytes(changed),
                        provenance_sha256=provenance_sha256,
                        candidate_sha256=candidate_sha256,
                    )

    def test_continuous_prior_release_requires_exact_reviewed_handoff(
        self,
    ) -> None:
        reservation = next(
            item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
        )
        provenance = (
            first_introduction_input().manifest_bytes
        )
        provenance_sha256 = hashlib.sha256(provenance).hexdigest()
        candidate_sha256 = "c" * 64
        prior_ledger = release_ledger.empty_release_ledger_bytes()
        review = release_review_bytes(
            provenance_sha256=provenance_sha256,
            candidate_sha256=candidate_sha256,
        )
        handoff = release_ledger.build_release_handoff_bytes(
            release_id="release-previous",
            ledger_bytes=prior_ledger,
            review_bytes=review,
            provenance_sha256=provenance_sha256,
            candidate_sha256=candidate_sha256,
            archive_manifest_sha256="a" * 64,
            archive_sha256="b" * 64,
        )
        evidence = release_ledger.ContinuousPriorReleaseInput(
            ledger_bytes=prior_ledger,
            review_bytes=review,
            handoff_bytes=handoff,
        )
        decision = release_ledger.evaluate_unreleased_regeneration(
            workflow_id="full",
            workflow_version=3,
            bundle_sha256=str(reservation["bundle_sha256"]),
            ledger_bytes=prior_ledger,
            activation_profiles=(),
            continuous_prior_release=evidence,
        )
        self.assertTrue(decision.allowed)

        forged = json.loads(handoff)
        forged["ledger_sha256"] = "0" * 64
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.evaluate_unreleased_regeneration(
                workflow_id="full",
                workflow_version=3,
                bundle_sha256=str(reservation["bundle_sha256"]),
                ledger_bytes=prior_ledger,
                activation_profiles=(),
                continuous_prior_release=(
                    release_ledger.ContinuousPriorReleaseInput(
                        ledger_bytes=prior_ledger,
                        review_bytes=review,
                        handoff_bytes=(
                            release_ledger.canonical_json_bytes(
                                forged
                            )
                        ),
                    )
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "RELEASE_HANDOFF_LEDGER_MISMATCH",
        )

        other = next(
            item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
            if not (
                item["workflow_id"] == "full"
                and item["workflow_version"] == 3
            )
        )
        nonempty_prior = (
            release_ledger.append_release_reservations(
                prior_ledger, (other,)
            )
        )
        nonempty_handoff = (
            release_ledger.build_release_handoff_bytes(
                release_id="release-discontinuous",
                ledger_bytes=nonempty_prior,
                review_bytes=review,
                provenance_sha256=provenance_sha256,
                candidate_sha256=candidate_sha256,
                archive_manifest_sha256="d" * 64,
                archive_sha256="e" * 64,
            )
        )
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.evaluate_unreleased_regeneration(
                workflow_id="full",
                workflow_version=3,
                bundle_sha256=str(reservation["bundle_sha256"]),
                ledger_bytes=prior_ledger,
                activation_profiles=(),
                continuous_prior_release=(
                    release_ledger.ContinuousPriorReleaseInput(
                        ledger_bytes=nonempty_prior,
                        review_bytes=review,
                        handoff_bytes=nonempty_handoff,
                    )
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "RELEASE_LEDGER_HISTORY_MUTATED",
        )


class ReleaseLedgerSuccessorTests(unittest.TestCase):
    def test_first_introduction_is_fixed_history_under_package_superset(
        self,
    ) -> None:
        source = FIRST_INTRODUCTION_PATH.read_bytes()
        original = json.loads(source)
        handler_identity, handler_reservation = synthetic_handler(
            "future",
            version=4,
        )
        reservation = synthetic_reservation(
            "future",
            4,
            handler_reservation,
        )
        with synthetic_package(
            [{"workflow_id": "future", "workflow_version": 4}],
            [handler_identity],
            [reservation],
        ):
            manifest, digest = (
                release_ledger.validate_first_introduction_bytes(
                    source,
                    repository=ROOT,
                    plugin_root=ROOT,
                )
            )
        self.assertEqual(manifest, original)
        self.assertEqual(
            digest,
            release_ledger.FIRST_INTRODUCTION_MANIFEST_SHA256,
        )

    def test_first_introduction_history_tamper_matrix_is_rejected(
        self,
    ) -> None:
        source = FIRST_INTRODUCTION_PATH.read_bytes()
        original = json.loads(source)
        workflow = original["introduced_workflows"]
        handlers = original["introduced_handlers"]
        replacement_workflow = {
            "workflow_id": "replacement",
            "workflow_version": 9,
        }
        replacement_handler = {
            "registry": "commands",
            "id": "command.replacement/v9",
            "version": "v9",
            "contract_id": "dev-flow-command/v1",
        }
        cases = {
            "workflow-delete": {
                **original,
                "introduced_workflows": workflow[1:],
            },
            "workflow-add": {
                **original,
                "introduced_workflows": sorted(
                    [*workflow, replacement_workflow],
                    key=release_ledger._workflow_sort_key,
                ),
            },
            "workflow-duplicate": {
                **original,
                "introduced_workflows": [workflow[0], *workflow],
            },
            "workflow-reorder": {
                **original,
                "introduced_workflows": list(reversed(workflow)),
            },
            "workflow-replace": {
                **original,
                "introduced_workflows": sorted(
                    [replacement_workflow, *workflow[1:]],
                    key=release_ledger._workflow_sort_key,
                ),
            },
            "handler-delete": {
                **original,
                "introduced_handlers": handlers[1:],
            },
            "handler-add": {
                **original,
                "introduced_handlers": sorted(
                    [*handlers, replacement_handler],
                    key=release_ledger._handler_sort_key,
                ),
            },
            "handler-duplicate": {
                **original,
                "introduced_handlers": [handlers[0], *handlers],
            },
            "handler-reorder": {
                **original,
                "introduced_handlers": list(reversed(handlers)),
            },
            "handler-replace": {
                **original,
                "introduced_handlers": sorted(
                    [replacement_handler, *handlers[1:]],
                    key=release_ledger._handler_sort_key,
                ),
            },
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                replacement = release_ledger.canonical_json_bytes(
                    candidate
                )
                self.assertNotEqual(
                    hashlib.sha256(replacement).hexdigest(),
                    release_ledger.FIRST_INTRODUCTION_MANIFEST_SHA256,
                )
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ):
                    release_ledger.validate_first_introduction_bytes(
                        replacement,
                        repository=ROOT,
                        plugin_root=ROOT,
                    )

    def test_first_introduction_rejects_missing_historical_identity(
        self,
    ) -> None:
        source = FIRST_INTRODUCTION_PATH.read_bytes()
        workflows, handlers = (
            release_ledger.discover_introduced_identity_keys(ROOT)
        )
        cases = {
            "workflow": (workflows[1:], handlers),
            "handler": (workflows, handlers[1:]),
        }
        for label, identities in cases.items():
            with self.subTest(label=label), mock.patch.object(
                release_ledger,
                "discover_introduced_identity_keys",
                return_value=identities,
            ):
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ) as raised:
                    release_ledger.validate_first_introduction_bytes(
                        source,
                        repository=ROOT,
                        plugin_root=ROOT,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "FIRST_INTRODUCTION_IDENTITY_SET_MISMATCH",
                )

    def test_reserved_v3_prefix_tamper_matrix_is_rejected(
        self,
    ) -> None:
        source = reserved_v3_ledger_bytes()
        original = json.loads(source)
        replacements = {}
        deleted = json.loads(source)
        del deleted["reservations"][0]
        replacements["delete"] = deleted
        changed = json.loads(source)
        changed["reservations"][0]["graph_sha256"] = "0" * 64
        replacements["modify"] = changed
        replaced = json.loads(source)
        replaced["reservations"][0] = dict(
            replaced["reservations"][1]
        )
        replaced["reservations"][0]["workflow_id"] = "replacement"
        replacements["replace"] = replaced
        reordered = json.loads(source)
        reordered["reservations"][0:2] = reversed(
            reordered["reservations"][0:2]
        )
        replacements["reorder"] = reordered
        for label, candidate in replacements.items():
            with self.subTest(label=label):
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ) as raised:
                    release_ledger.validate_reserved_v3_ledger_bytes(
                        release_ledger.canonical_json_bytes(candidate),
                        plugin_root=ROOT,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "RESERVED_V3_LEDGER_MISMATCH",
                )
        validated = release_ledger.validate_reserved_v3_ledger_bytes(
            source,
            plugin_root=ROOT,
        )
        self.assertEqual(
            len(validated["reservations"]),
            release_ledger.RESERVED_V3_RESERVATION_COUNT,
        )

    def test_append_batch_rejects_empty_duplicate_overlap_and_order(
        self,
    ) -> None:
        empty = release_ledger.empty_release_ledger_bytes()
        handler_a, reservation_handler_a = synthetic_handler(
            "a",
            version=4,
        )
        handler_b, reservation_handler_b = synthetic_handler(
            "b",
            version=4,
        )
        del handler_a, handler_b
        reservation_a = synthetic_reservation(
            "a",
            4,
            reservation_handler_a,
        )
        reservation_b = synthetic_reservation(
            "b",
            4,
            reservation_handler_b,
        )
        with self.assertRaises(release_ledger.ReleaseLedgerError) as raised:
            release_ledger.append_release_reservations(empty, ())
        self.assertEqual(
            raised.exception.code,
            "RELEASE_LEDGER_APPEND_BATCH_EMPTY",
        )
        duplicate = (reservation_a, reservation_a)
        with self.assertRaises(release_ledger.ReleaseLedgerError) as raised:
            release_ledger.append_release_reservations(empty, duplicate)
        self.assertEqual(
            raised.exception.code,
            "RELEASE_RESERVATION_DUPLICATE",
        )
        historical = reserved_v3_ledger_bytes()
        historical_item = json.loads(historical)["reservations"][0]
        with self.assertRaises(release_ledger.ReleaseLedgerError) as raised:
            release_ledger.append_release_reservations(
                historical,
                (historical_item,),
            )
        self.assertEqual(
            raised.exception.code,
            "RELEASE_RESERVATION_DUPLICATE",
        )
        with self.assertRaises(release_ledger.ReleaseLedgerError) as raised:
            release_ledger.append_release_reservations(
                empty,
                (reservation_b, reservation_a),
            )
        self.assertEqual(
            raised.exception.code,
            "RELEASE_LEDGER_APPEND_BATCH_ORDER_INVALID",
        )

    def test_separately_sorted_batches_are_not_globally_reordered(
        self,
    ) -> None:
        _zeta_handler, zeta_reservation_handler = synthetic_handler(
            "zeta",
            version=4,
        )
        _alpha_handler, alpha_reservation_handler = synthetic_handler(
            "alpha",
            version=5,
        )
        zeta = synthetic_reservation(
            "zeta",
            4,
            zeta_reservation_handler,
        )
        alpha = synthetic_reservation(
            "alpha",
            5,
            alpha_reservation_handler,
        )
        first = release_ledger.append_release_reservations(
            reserved_v3_ledger_bytes(),
            (zeta,),
        )
        second = release_ledger.append_release_reservations(
            first,
            (alpha,),
        )
        validated = release_ledger.validate_release_ledger_bytes(
            second,
            previous_ledger_bytes=first,
        )
        suffix = validated["reservations"][-2:]
        self.assertEqual(
            [
                (item["workflow_id"], item["workflow_version"])
                for item in suffix
            ],
            [("zeta", 4), ("alpha", 5)],
        )
        self.assertNotEqual(
            suffix,
            sorted(suffix, key=release_ledger._workflow_sort_key),
        )

    def test_append_iterables_are_materialized_once(self) -> None:
        _handler, reservation_handler = synthetic_handler(
            "one-shot",
            version=4,
        )
        reservation = synthetic_reservation(
            "one-shot",
            4,
            reservation_handler,
        )

        class OneShot:
            def __init__(self) -> None:
                self.iterations = 0

            def __iter__(self):
                self.iterations += 1
                if self.iterations > 1:
                    raise AssertionError("iterable consumed twice")
                yield reservation

        append_input = OneShot()
        release_ledger.append_release_reservations(
            release_ledger.empty_release_ledger_bytes(),
            append_input,
        )
        self.assertEqual(append_input.iterations, 1)
        digest_input = OneShot()
        release_ledger.introduction_epoch_append_batch_sha256(
            digest_input
        )
        self.assertEqual(digest_input.iterations, 1)

    def test_append_digest_covers_complete_reservation_objects(
        self,
    ) -> None:
        _handler, reservation_handler = synthetic_handler(
            "digest",
            version=4,
        )
        reservation = synthetic_reservation(
            "digest",
            4,
            reservation_handler,
        )
        baseline = (
            release_ledger.introduction_epoch_append_batch_sha256(
                (reservation,)
            )
        )
        mutations = []
        for field in ("graph_sha256", "bundle_sha256"):
            changed = json.loads(json.dumps(reservation))
            changed[field] = "0" * 64
            mutations.append(changed)
        changed_contract = json.loads(json.dumps(reservation))
        changed_contract["handlers"][0][
            "contract_id"
        ] = "dev-flow-command/v2"
        mutations.append(changed_contract)
        changed_implementation = json.loads(json.dumps(reservation))
        changed_implementation["handlers"][0][
            "implementation_sha256"
        ] = "0" * 64
        mutations.append(changed_implementation)
        for changed in mutations:
            self.assertNotEqual(
                release_ledger.introduction_epoch_append_batch_sha256(
                    (changed,)
                ),
                baseline,
            )


class IntroductionEpochTests(unittest.TestCase):
    def test_packaged_v4_successor_epoch_and_ledger_validate(
        self,
    ) -> None:
        ledger_bytes = RESERVED_V3_LEDGER_PATH.read_bytes()
        manifest, digest = (
            release_ledger.validate_introduction_epoch_bytes(
                (
                    ROOT
                    / "workflows"
                    / "release-provenance"
                    / "introduction-epochs"
                    / "introduction-epoch-1.json"
                ).read_bytes(),
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=reserved_v3_ledger_bytes(),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=ledger_bytes,
                repository=ROOT,
                plugin_root=ROOT,
            )
        )
        self.assertEqual(
            digest,
            "6d92f8453d1fc76bebcc832abe114ffa3"
            "cc75af7bf39cb776a4efa89ca9824ac",
        )
        self.assertEqual(manifest["predecessor_kind"], "reserved-unexposed")
        self.assertEqual(manifest["append_batch_count"], 2)
        self.assertEqual(
            manifest["result_ledger_sha256"],
            hashlib.sha256(ledger_bytes).hexdigest(),
        )
        validated = release_ledger.validate_ledger_against_package(
            ledger_bytes,
            plugin_root=ROOT,
        )
        self.assertEqual(len(validated["reservations"]), 6)

    def _validate_reserved_fixture(
        self,
        epoch: bytes,
        result_ledger: bytes,
        workflow: dict[str, object],
        handler: dict[str, object],
        reservation: dict[str, object],
    ) -> tuple[release_ledger.IntroductionEpochValidation, ...]:
        with synthetic_package(
            [workflow],
            [handler],
            [reservation],
        ):
            return release_ledger.validate_introduction_epoch_chain(
                (
                    release_ledger.IntroductionEpochProvenanceInput(
                        manifest_bytes=epoch,
                        result_ledger_bytes=result_ledger,
                    ),
                ),
                first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                reserved_v3_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                reserved_v3_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                repository=ROOT,
                plugin_root=ROOT,
            )

    def test_reserved_unexposed_epoch_binds_complete_successor(
        self,
    ) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        validations = self._validate_reserved_fixture(
            epoch,
            result_ledger,
            workflow,
            handler,
            reservation,
        )
        self.assertEqual(len(validations), 1)
        validated = validations[0]
        manifest = validated.manifest
        self.assertEqual(
            manifest["predecessor_kind"],
            release_ledger.INTRODUCTION_EPOCH_RESERVED_UNEXPOSED,
        )
        self.assertEqual(
            manifest["predecessor_ledger_sha256"],
            release_ledger.RESERVED_V3_LEDGER_SHA256,
        )
        self.assertEqual(
            manifest["predecessor_reservation_count"],
            release_ledger.RESERVED_V3_RESERVATION_COUNT,
        )
        self.assertEqual(
            manifest["result_ledger_sha256"],
            hashlib.sha256(result_ledger).hexdigest(),
        )
        self.assertFalse(validated.authorizes_exposure)
        self.assertEqual(
            manifest["introduced_workflows"],
            [workflow],
        )
        self.assertEqual(
            manifest["introduced_handlers"],
            [handler],
        )
        with synthetic_package(
            [workflow],
            [handler],
            [reservation],
        ):
            single, digest = (
                release_ledger.validate_introduction_epoch_bytes(
                    epoch,
                    predecessor_first_introduction_bytes=(
                        FIRST_INTRODUCTION_PATH.read_bytes()
                    ),
                    predecessor_ledger_bytes=(
                        reserved_v3_ledger_bytes()
                    ),
                    predecessor_activation_bytes=(
                        RESERVED_V3_ACTIVATION_PATH.read_bytes()
                    ),
                    current_ledger_bytes=result_ledger,
                    repository=ROOT,
                    plugin_root=ROOT,
                )
            )
        self.assertEqual(single, manifest)
        self.assertEqual(digest, validated.provenance_sha256)

    def test_epoch_chain_generator_is_materialized_once(self) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        entry = release_ledger.IntroductionEpochProvenanceInput(
            manifest_bytes=epoch,
            result_ledger_bytes=result_ledger,
        )

        class OneShot:
            def __init__(self) -> None:
                self.iterations = 0

            def __iter__(self):
                self.iterations += 1
                if self.iterations > 1:
                    raise AssertionError("chain consumed twice")
                yield entry

        chain = OneShot()
        with synthetic_package(
            [workflow],
            [handler],
            [reservation],
        ):
            release_ledger.validate_introduction_epoch_chain(
                chain,
                first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                reserved_v3_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                reserved_v3_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                repository=ROOT,
                plugin_root=ROOT,
            )
        self.assertEqual(chain.iterations, 1)

    def test_epoch_binding_tamper_matrix_is_rejected(self) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        original = json.loads(epoch)
        cases = {}
        scalar_replacements = {
            "schema": "unsupported/v1",
            "change_id": "other-change",
            "predecessor_provenance_sha256": "0" * 64,
            "predecessor_ledger_sha256": "0" * 64,
            "predecessor_reservation_count": 3,
            "predecessor_first_introduction_sha256": "0" * 64,
            "predecessor_activation_sha256": "0" * 64,
            "git_object_format": "sha256",
            "base_commit": "0" * 40,
            "base_tree": "0" * 40,
            "inventory_contract": "other-inventory/v1",
            "inventory_sha256": "0" * 64,
            "append_batch_start": 3,
            "append_batch_count": 2,
            "append_batch_sha256": "0" * 64,
            "result_ledger_sha256": "0" * 64,
            "cumulative_identity_set_sha256": "0" * 64,
        }
        for field, value in scalar_replacements.items():
            cases[field] = {**original, field: value}
        cases["sequence"] = {
            **original,
            "epoch_id": "introduction-epoch-2",
            "epoch_sequence": 2,
        }
        cases["epoch-id"] = {
            **original,
            "epoch_id": "replacement-epoch",
        }
        for field in (
            "reviewed",
            "handoff",
            "published",
            "installed",
            "activated",
            "pin_eligible",
        ):
            cases[field] = {**original, field: True}
        for label, candidate in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ):
                    self._validate_reserved_fixture(
                        release_ledger.canonical_json_bytes(candidate),
                        result_ledger,
                        workflow,
                        handler,
                        reservation,
                    )

    def test_introduced_identity_delta_must_be_exact(self) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        original = json.loads(epoch)
        historical = json.loads(
            FIRST_INTRODUCTION_PATH.read_bytes()
        )
        cases = {
            "workflow-omit": {
                **original,
                "introduced_workflows": [],
            },
            "workflow-historical-overlap": {
                **original,
                "introduced_workflows": [
                    historical["introduced_workflows"][0],
                    workflow,
                ],
            },
            "workflow-duplicate": {
                **original,
                "introduced_workflows": [workflow, workflow],
            },
            "handler-omit": {
                **original,
                "introduced_handlers": [],
            },
            "handler-historical-overlap": {
                **original,
                "introduced_handlers": [
                    historical["introduced_handlers"][0],
                    handler,
                ],
            },
            "handler-duplicate": {
                **original,
                "introduced_handlers": [handler, handler],
            },
        }
        for label, candidate in cases.items():
            candidate["introduced_workflows"] = sorted(
                candidate["introduced_workflows"],
                key=release_ledger._workflow_sort_key,
            )
            candidate["introduced_handlers"] = sorted(
                candidate["introduced_handlers"],
                key=release_ledger._handler_sort_key,
            )
            with self.subTest(label=label):
                with self.assertRaises(
                    release_ledger.ReleaseLedgerError
                ):
                    self._validate_reserved_fixture(
                        release_ledger.canonical_json_bytes(candidate),
                        result_ledger,
                        workflow,
                        handler,
                        reservation,
                    )

    def test_suffix_must_match_keys_and_package_recomputation(
        self,
    ) -> None:
        epoch, _result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        forged = json.loads(json.dumps(reservation))
        forged["bundle_sha256"] = "0" * 64
        forged_ledger = release_ledger.append_release_reservations(
            reserved_v3_ledger_bytes(),
            (forged,),
        )
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            self._validate_reserved_fixture(
                epoch,
                forged_ledger,
                workflow,
                handler,
                reservation,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_APPEND_BATCH_MISMATCH",
        )

        _other_handler, other_reservation_handler = synthetic_handler(
            "other",
            version=4,
        )
        other = synthetic_reservation(
            "other",
            4,
            other_reservation_handler,
        )
        wrong_key_ledger = release_ledger.append_release_reservations(
            reserved_v3_ledger_bytes(),
            (other,),
        )
        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            self._validate_reserved_fixture(
                epoch,
                wrong_key_ledger,
                workflow,
                handler,
                reservation,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_WORKFLOW_SUFFIX_MISMATCH",
        )

        with self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            self._validate_reserved_fixture(
                epoch,
                reserved_v3_ledger_bytes(),
                workflow,
                handler,
                reservation,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_APPEND_BATCH_EMPTY",
        )

    def test_cumulative_digest_uses_complete_provenance_history(
        self,
    ) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        validation = self._validate_reserved_fixture(
            epoch,
            result_ledger,
            workflow,
            handler,
            reservation,
        )[0]
        first = json.loads(FIRST_INTRODUCTION_PATH.read_bytes())
        full_digest = (
            release_ledger.introduction_epoch_cumulative_identity_set_sha256(
                sorted(
                    [*first["introduced_workflows"], workflow],
                    key=release_ledger._workflow_sort_key,
                ),
                sorted(
                    [*first["introduced_handlers"], handler],
                    key=release_ledger._handler_sort_key,
                ),
            )
        )
        ledger = json.loads(reserved_v3_ledger_bytes())
        ledger_handlers = {
            release_ledger._handler_sort_key(item): {
                field: item[field]
                for field in ("registry", "id", "version", "contract_id")
            }
            for reservation_item in ledger["reservations"]
            for item in reservation_item["handlers"]
        }
        union_digest = (
            release_ledger.introduction_epoch_cumulative_identity_set_sha256(
                [*first["introduced_workflows"], workflow],
                sorted(
                    [*ledger_handlers.values(), handler],
                    key=release_ledger._handler_sort_key,
                ),
            )
        )
        self.assertEqual(
            validation.cumulative_identity_set_sha256,
            full_digest,
        )
        self.assertNotEqual(full_digest, union_digest)

    def test_new_handler_outside_suffix_closure_is_rejected(
        self,
    ) -> None:
        handler, reservation_handler = synthetic_handler(
            "covered",
            version=4,
        )
        orphan, _orphan_reservation = synthetic_handler(
            "orphan",
            version=4,
        )
        workflow = {
            "workflow_id": "covered",
            "workflow_version": 4,
        }
        reservation = synthetic_reservation(
            "covered",
            4,
            reservation_handler,
        )
        result_ledger = release_ledger.append_release_reservations(
            reserved_v3_ledger_bytes(),
            (reservation,),
        )
        with synthetic_package(
            [workflow],
            [handler, orphan],
            [reservation],
        ), self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.build_introduction_epoch_bytes(
                epoch_id="introduction-epoch-1",
                epoch_sequence=1,
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=result_ledger,
                repository=ROOT,
                plugin_root=ROOT,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_HANDLER_DELTA_MISMATCH",
        )

    def test_continuous_official_release_epoch_chain(self) -> None:
        epoch1, ledger1, workflow1, handler1, reservation1 = (
            build_reserved_epoch_fixture("zeta", 4)
        )
        provenance1_sha256 = hashlib.sha256(epoch1).hexdigest()
        candidate1_sha256 = "c" * 64
        review1 = release_review_bytes(
            provenance_sha256=provenance1_sha256,
            candidate_sha256=candidate1_sha256,
        )
        handoff1 = release_ledger.build_release_handoff_bytes(
            release_id="release-epoch-1",
            ledger_bytes=ledger1,
            review_bytes=review1,
            provenance_sha256=provenance1_sha256,
            candidate_sha256=candidate1_sha256,
            archive_manifest_sha256="a" * 64,
            archive_sha256="b" * 64,
        )
        handler2, reservation_handler2 = synthetic_handler(
            "alpha",
            version=5,
        )
        workflow2 = {
            "workflow_id": "alpha",
            "workflow_version": 5,
        }
        reservation2 = synthetic_reservation(
            "alpha",
            5,
            reservation_handler2,
        )
        ledger2 = release_ledger.append_release_reservations(
            ledger1,
            (reservation2,),
        )
        prior = release_ledger.IntroductionEpochProvenanceInput(
            manifest_bytes=epoch1,
            result_ledger_bytes=ledger1,
        )
        with synthetic_package(
            [workflow1, workflow2],
            [handler1, handler2],
            [reservation1, reservation2],
        ):
            epoch2 = release_ledger.build_introduction_epoch_bytes(
                epoch_id="introduction-epoch-2",
                epoch_sequence=2,
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=ledger2,
                repository=ROOT,
                plugin_root=ROOT,
                prior_epochs=(prior,),
                predecessor_review_bytes=review1,
                predecessor_handoff_bytes=handoff1,
            )
            validations = (
                release_ledger.validate_introduction_epoch_chain(
                    (
                        prior,
                        release_ledger.IntroductionEpochProvenanceInput(
                            manifest_bytes=epoch2,
                            result_ledger_bytes=ledger2,
                            predecessor_review_bytes=review1,
                            predecessor_handoff_bytes=handoff1,
                        ),
                    ),
                    first_introduction_bytes=(
                        FIRST_INTRODUCTION_PATH.read_bytes()
                    ),
                    reserved_v3_ledger_bytes=(
                        reserved_v3_ledger_bytes()
                    ),
                    reserved_v3_activation_bytes=(
                        RESERVED_V3_ACTIVATION_PATH.read_bytes()
                    ),
                    repository=ROOT,
                    plugin_root=ROOT,
                )
            )
        self.assertEqual(len(validations), 2)
        self.assertEqual(
            validations[1].manifest["predecessor_kind"],
            release_ledger.INTRODUCTION_EPOCH_OFFICIAL_RELEASE,
        )
        self.assertEqual(
            validations[1].manifest[
                "predecessor_provenance_sha256"
            ],
            provenance1_sha256,
        )
        combined_suffix = json.loads(ledger2)["reservations"][-2:]
        self.assertEqual(
            [
                (item["workflow_id"], item["workflow_version"])
                for item in combined_suffix
            ],
            [("zeta", 4), ("alpha", 5)],
        )
        self.assertNotEqual(
            combined_suffix,
            sorted(
                combined_suffix,
                key=release_ledger._workflow_sort_key,
            ),
        )

        with synthetic_package(
            [workflow1, workflow2],
            [handler1, handler2],
            [reservation1, reservation2],
        ):
            with self.assertRaises(
                release_ledger.ReleaseLedgerError
            ) as raised:
                release_ledger.validate_introduction_epoch_bytes(
                    epoch2,
                    predecessor_first_introduction_bytes=(
                        FIRST_INTRODUCTION_PATH.read_bytes()
                    ),
                    predecessor_ledger_bytes=(
                        reserved_v3_ledger_bytes()
                    ),
                    predecessor_activation_bytes=(
                        RESERVED_V3_ACTIVATION_PATH.read_bytes()
                    ),
                    current_ledger_bytes=ledger2,
                    repository=ROOT,
                    plugin_root=ROOT,
                    prior_epochs=(prior,),
                )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_OFFICIAL_EVIDENCE_MISSING",
        )

        forged_handoff = json.loads(handoff1)
        forged_handoff["review_sha256"] = "0" * 64
        with synthetic_package(
            [workflow1, workflow2],
            [handler1, handler2],
            [reservation1, reservation2],
        ), self.assertRaises(release_ledger.ReleaseLedgerError):
            release_ledger.validate_introduction_epoch_bytes(
                epoch2,
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=ledger2,
                repository=ROOT,
                plugin_root=ROOT,
                prior_epochs=(prior,),
                predecessor_review_bytes=review1,
                predecessor_handoff_bytes=(
                    release_ledger.canonical_json_bytes(
                        forged_handoff
                    )
                ),
            )

    def test_handler_introduction_cannot_be_deferred_to_later_epoch(
        self,
    ) -> None:
        epoch1, ledger1, workflow1, handler1, reservation1 = (
            build_reserved_epoch_fixture("zeta", 4)
        )
        provenance1_sha256 = hashlib.sha256(epoch1).hexdigest()
        candidate1_sha256 = "c" * 64
        review1 = release_review_bytes(
            provenance_sha256=provenance1_sha256,
            candidate_sha256=candidate1_sha256,
        )
        handoff1 = release_ledger.build_release_handoff_bytes(
            release_id="release-epoch-1",
            ledger_bytes=ledger1,
            review_bytes=review1,
            provenance_sha256=provenance1_sha256,
            candidate_sha256=candidate1_sha256,
            archive_manifest_sha256="a" * 64,
            archive_sha256="b" * 64,
        )
        handler2, reservation_handler2 = synthetic_handler(
            "alpha",
            version=5,
        )
        reservation2 = synthetic_reservation(
            "alpha",
            5,
            reservation_handler2,
        )
        reservation2["handlers"] = sorted(
            [
                reservation1["handlers"][0],
                reservation_handler2,
            ],
            key=release_ledger._handler_sort_key,
        )
        workflow2 = {
            "workflow_id": "alpha",
            "workflow_version": 5,
        }
        ledger2 = release_ledger.append_release_reservations(
            ledger1,
            (reservation2,),
        )
        prior = release_ledger.IntroductionEpochProvenanceInput(
            manifest_bytes=epoch1,
            result_ledger_bytes=ledger1,
        )
        with synthetic_package(
            [workflow1, workflow2],
            [handler1, handler2],
            [reservation1, reservation2],
        ):
            epoch2 = release_ledger.build_introduction_epoch_bytes(
                epoch_id="introduction-epoch-2",
                epoch_sequence=2,
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=ledger2,
                repository=ROOT,
                plugin_root=ROOT,
                prior_epochs=(prior,),
                predecessor_review_bytes=review1,
                predecessor_handoff_bytes=handoff1,
            )

        malicious_epoch1 = json.loads(epoch1)
        malicious_epoch1["introduced_handlers"] = []
        first = json.loads(FIRST_INTRODUCTION_PATH.read_bytes())
        malicious_epoch1["cumulative_identity_set_sha256"] = (
            release_ledger.introduction_epoch_cumulative_identity_set_sha256(
                sorted(
                    [*first["introduced_workflows"], workflow1],
                    key=release_ledger._workflow_sort_key,
                ),
                first["introduced_handlers"],
            )
        )
        malicious_epoch1_bytes = release_ledger.canonical_json_bytes(
            malicious_epoch1
        )
        malicious_provenance1_sha256 = hashlib.sha256(
            malicious_epoch1_bytes
        ).hexdigest()
        malicious_review1 = release_review_bytes(
            provenance_sha256=malicious_provenance1_sha256,
            candidate_sha256=candidate1_sha256,
        )
        malicious_handoff1 = release_ledger.build_release_handoff_bytes(
            release_id="release-epoch-1",
            ledger_bytes=ledger1,
            review_bytes=malicious_review1,
            provenance_sha256=malicious_provenance1_sha256,
            candidate_sha256=candidate1_sha256,
            archive_manifest_sha256="a" * 64,
            archive_sha256="b" * 64,
        )
        malicious_epoch2 = json.loads(epoch2)
        malicious_epoch2["predecessor_provenance_sha256"] = (
            malicious_provenance1_sha256
        )
        malicious_epoch2["predecessor_review_sha256"] = hashlib.sha256(
            malicious_review1
        ).hexdigest()
        malicious_epoch2["predecessor_handoff_sha256"] = hashlib.sha256(
            malicious_handoff1
        ).hexdigest()
        malicious_epoch2["introduced_handlers"] = sorted(
            [handler1, handler2],
            key=release_ledger._handler_sort_key,
        )
        with synthetic_package(
            [workflow1, workflow2],
            [handler1, handler2],
            [reservation1, reservation2],
        ), self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.validate_introduction_epoch_chain(
                (
                    release_ledger.IntroductionEpochProvenanceInput(
                        manifest_bytes=malicious_epoch1_bytes,
                        result_ledger_bytes=ledger1,
                    ),
                    release_ledger.IntroductionEpochProvenanceInput(
                        manifest_bytes=(
                            release_ledger.canonical_json_bytes(
                                malicious_epoch2
                            )
                        ),
                        result_ledger_bytes=ledger2,
                        predecessor_review_bytes=malicious_review1,
                        predecessor_handoff_bytes=malicious_handoff1,
                    ),
                ),
                first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                reserved_v3_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                reserved_v3_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                repository=ROOT,
                plugin_root=ROOT,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_HANDLER_DELTA_MISMATCH",
        )
        json.dumps(raised.exception.as_dict())

    def test_reserved_unexposed_facts_never_authorize_exposure(
        self,
    ) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        validation = self._validate_reserved_fixture(
            epoch,
            result_ledger,
            workflow,
            handler,
            reservation,
        )[0]
        self.assertFalse(validation.authorizes_exposure)
        fake_review = release_review_bytes(
            provenance_sha256=hashlib.sha256(epoch).hexdigest(),
            candidate_sha256="c" * 64,
        )
        fake_handoff = release_ledger.build_release_handoff_bytes(
            release_id="fake-v3-handoff",
            ledger_bytes=result_ledger,
            review_bytes=fake_review,
            provenance_sha256=hashlib.sha256(epoch).hexdigest(),
            candidate_sha256="c" * 64,
            archive_manifest_sha256="a" * 64,
            archive_sha256="b" * 64,
        )
        with synthetic_package(
            [workflow],
            [handler],
            [reservation],
        ), self.assertRaises(
            release_ledger.ReleaseLedgerError
        ) as raised:
            release_ledger.build_introduction_epoch_bytes(
                epoch_id="introduction-epoch-1",
                epoch_sequence=1,
                predecessor_first_introduction_bytes=(
                    FIRST_INTRODUCTION_PATH.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    reserved_v3_ledger_bytes()
                ),
                predecessor_activation_bytes=(
                    RESERVED_V3_ACTIVATION_PATH.read_bytes()
                ),
                current_ledger_bytes=result_ledger,
                repository=ROOT,
                plugin_root=ROOT,
                predecessor_review_bytes=fake_review,
                predecessor_handoff_bytes=fake_handoff,
            )
        self.assertEqual(
            raised.exception.code,
            "INTRODUCTION_EPOCH_FALSE_HANDOFF",
        )

    def test_successor_validation_preserves_v3_parseability(
        self,
    ) -> None:
        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        self._validate_reserved_fixture(
            epoch,
            result_ledger,
            workflow,
            handler,
            reservation,
        )
        ledger = release_ledger.validate_ledger_against_package(
            reserved_v3_ledger_bytes(),
            plugin_root=ROOT,
        )
        package = {
            (
                item["workflow_id"],
                item["workflow_version"],
            ): item
            for item in release_ledger.package_release_reservations(
                ROOT
            )
        }
        for historical in ledger["reservations"]:
            key = (
                historical["workflow_id"],
                historical["workflow_version"],
            )
            self.assertEqual(package[key], historical)

    def test_epoch_cli_and_exports_are_public(self) -> None:
        required_exports = {
            "IntroductionEpochProvenanceInput",
            "IntroductionEpochValidation",
            "build_introduction_epoch_bytes",
            "introduction_epoch_append_batch_sha256",
            "introduction_epoch_cumulative_identity_set_sha256",
            "validate_introduction_epoch_bytes",
            "validate_introduction_epoch_chain",
            "validate_reserved_v3_ledger_bytes",
        }
        self.assertTrue(required_exports <= set(release_ledger.__all__))
        parsed = release_ledger._parser().parse_args(
            [
                "validate-introduction-epoch",
                "--plugin-root",
                str(ROOT),
                "--repository",
                str(ROOT),
                "--first-introduction",
                str(FIRST_INTRODUCTION_PATH),
                "--reserved-v3-ledger",
                str(RESERVED_V3_LEDGER_PATH),
                "--reserved-v3-activation",
                str(RESERVED_V3_ACTIVATION_PATH),
                "--manifest",
                str(FIRST_INTRODUCTION_PATH),
                "--result-ledger",
                str(RESERVED_V3_LEDGER_PATH),
            ]
        )
        self.assertEqual(parsed.command, "validate-introduction-epoch")

        epoch, result_ledger, workflow, handler, reservation = (
            build_reserved_epoch_fixture()
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "epoch.json"
            ledger_path = root / "ledger.json"
            manifest_path.write_bytes(epoch)
            ledger_path.write_bytes(result_ledger)
            output = io.StringIO()
            with synthetic_package(
                [workflow],
                [handler],
                [reservation],
            ), redirect_stdout(output):
                result = release_ledger.main(
                    [
                        "validate-introduction-epoch",
                        "--plugin-root",
                        str(ROOT),
                        "--repository",
                        str(ROOT),
                        "--first-introduction",
                        str(FIRST_INTRODUCTION_PATH),
                        "--reserved-v3-ledger",
                        str(RESERVED_V3_LEDGER_PATH),
                        "--reserved-v3-activation",
                        str(RESERVED_V3_ACTIVATION_PATH),
                        "--manifest",
                        str(manifest_path),
                        "--result-ledger",
                        str(ledger_path),
                    ]
                )
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["authorizes_exposure"])
        self.assertTrue(payload["supersession_review_required"])


if __name__ == "__main__":
    unittest.main()
