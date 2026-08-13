"""Shared version parsing and canonical release download rule tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys = __import__("sys")
sys.path.insert(0, str(ROOT / "scripts"))

import release_resolver  # noqa: E402


def _release_payload(version: str, *, draft=False, prerelease=False, assets=None):
    names = list(release_resolver.versioned_bootstrap_names(version)) if assets is None else assets
    return {
        "draft": draft,
        "prerelease": prerelease,
        "tag_name": "v" + version,
        "assets": [{"name": name} for name in names],
    }


class FakeResponse:
    def __init__(self, raw: bytes, *, url: str = "https://api.github.com/repos/Innocent-children/dev-flow-orchestrator/releases/latest"):
        self.raw = raw
        self.url = url
        self.closed = False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if self.raw is None:
            raise URLError("simulated network failure")
        chunk = self.raw[:size] if size > 0 else self.raw
        self.raw = self.raw[len(chunk):] if size > 0 else b""
        return chunk

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, responses, *, final_url=None):
        self.responses = list(responses)
        self.final_url = final_url
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if not self.responses:
            raise URLError("no response available")
        selected = self.responses.pop(0)
        if isinstance(selected, HTTPError):
            raise selected
        if isinstance(selected, Exception):
            raise selected
        return selected


class VersionParsingTests(unittest.TestCase):
    def test_latest_and_exact_semver_are_accepted(self) -> None:
        self.assertEqual(release_resolver.parse_version_request("latest"), "latest")
        self.assertEqual(release_resolver.parse_version_request("0.6.8"), "0.6.8")
        self.assertEqual(release_resolver.parse_version_request("10.0.0"), "10.0.0")

    def test_invalid_versions_are_rejected_without_any_download(self) -> None:
        for invalid in (
            "",
            "LATEST",
            " latest",
            "latest ",
            "0.6.8-with-prefix",
            "0.6",
            "0.6.8-rc1",
            "0.6.8+build",
            "00.1.2",
            "0.06.8",
            "0.6.8\n",
            "0.6.*",
            ">=0.6.8",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(release_resolver.ReleaseResolveError):
                    release_resolver.parse_version_request(invalid)
                with self.assertRaises(release_resolver.ReleaseResolveError):
                    release_resolver.validate_version(invalid)


class LatestResolutionTests(unittest.TestCase):
    def test_resolves_only_official_release_with_both_bootstraps(self) -> None:
        payload = _release_payload("0.7.0")
        opener = FakeOpener(
            [FakeResponse(json.dumps(payload, sort_keys=True).encode("utf-8"))]
        )
        self.assertEqual(release_resolver.resolve_latest_version(opener=opener), "0.7.0")
        self.assertEqual(opener.requests[0].full_url, release_resolver._latest_release_url())
        self.assertEqual(
            opener.requests[0].get_header("User-agent"), "dev-flow-release-resolver"
        )

    def test_draft_and_prerelease_entries_are_never_selected(self) -> None:
        for flag in ("draft", "prerelease"):
            payload = _release_payload("0.7.0", **{flag: True})
            opener = FakeOpener(
                [FakeResponse(json.dumps(payload, sort_keys=True).encode("utf-8"))]
            )
            with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "official"):
                release_resolver.resolve_latest_version(opener=opener)

    def test_tag_and_asset_set_must_match_the_resolved_version(self) -> None:
        payload = _release_payload("0.7.0")
        payload["tag_name"] = "0.7-tag"
        opener = FakeOpener([FakeResponse(json.dumps(payload).encode())])
        with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "tag"):
            release_resolver.resolve_latest_version(opener=opener)
        payload = _release_payload("0.7.0", assets=["install-0.7.0.sh"])
        opener = FakeOpener([FakeResponse(json.dumps(payload).encode())])
        with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "missing"):
            release_resolver.resolve_latest_version(opener=opener)

    def test_network_failure_and_bad_json_fail_before_any_local_state(self) -> None:
        opener = FakeOpener([URLError("simulated network failure")])
        with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "failed"):
            release_resolver.resolve_latest_version(opener=opener)
        opener = FakeOpener([FakeResponse(b"{broken\n")])
        with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "JSON"):
            release_resolver.resolve_latest_version(opener=opener)

    def test_non_finite_release_metadata_is_not_strict_json(self) -> None:
        opener = FakeOpener(
            [
                FakeResponse(
                    b'{"draft":false,"prerelease":false,"tag_name":NaN,"assets":[]}'
                )
            ]
        )
        with self.assertRaisesRegex(
            release_resolver.ReleaseResolveError, "non-finite|JSON"
        ):
            release_resolver.resolve_latest_version(opener=opener)

    def test_response_origin_must_stay_inside_canonical_hosts(self) -> None:
        payload = _release_payload("0.7.0")
        opener = FakeOpener(
            [FakeResponse(json.dumps(payload).encode(), url="https://evil.example.invalid/x")]
        )
        with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "hosts"):
            release_resolver.resolve_latest_version(opener=opener)


class BootstrapAcquisitionTests(unittest.TestCase):
    def test_exact_version_download_lands_in_installer_owned_staging(self) -> None:
        payload = b"#!/bin/sh\n# version-matched\n"
        opener = FakeOpener([FakeResponse(payload, url="https://github.com/release/asset")])
        with tempfile.TemporaryDirectory() as temporary:
            path = release_resolver.acquire_version_bootstrap(
                "0.7.0",
                windows=False,
                destination_dir=Path(temporary),
                opener=opener,
            )
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(path.name, "install-0.7.0.sh")
            self.assertIn(
                "releases/download/v" + "0.7.0" + "/install-0.7.0.sh",
                opener.requests[0].full_url,
            )

    def test_missing_release_is_404_and_changes_no_product_state(self) -> None:
        error = HTTPError(
            "https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v{release}/install-{release}.sh",
            404,
            "Not Found",
            None,
            None,
        )
        opener = FakeOpener([error])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "does not exist"):
                release_resolver.acquire_version_bootstrap(
                    "0.7.0",
                    windows=False,
                    destination_dir=Path(temporary),
                    opener=opener,
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_download_failure_removes_partial_staging_bytes(self) -> None:
        class FailingResponse(FakeResponse):
            def read(self, size=-1):
                raise URLError("simulated mid-transfer failure")

        opener = FakeOpener([FailingResponse(b"partial")])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "failed"):
                release_resolver.acquire_version_bootstrap(
                    "0.7.0",
                    windows=False,
                    destination_dir=Path(temporary),
                    opener=opener,
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_non_https_and_non_canonical_urls_are_refused(self) -> None:
        with mock.patch.object(
            release_resolver,
            "bootstrap_url",
            return_value="http://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v{release}/install-{release}.sh",
        ):
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "not HTTPS"):
                    release_resolver.acquire_version_bootstrap(
                        "0.7.0", windows=False, destination_dir=Path(temporary)
                    )
        with mock.patch.object(
            release_resolver,
            "bootstrap_url",
            return_value="https://mirror.example.invalid/dev-flow-orchestrator/releases/download/v{release}/install-{release}.sh",
        ):
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(release_resolver.ReleaseResolveError, "hosts"):
                    release_resolver.acquire_version_bootstrap(
                        "0.7.0", windows=False, destination_dir=Path(temporary)
                    )

    def test_resolve_request_pins_latest_to_one_concrete_version(self) -> None:
        payload = _release_payload("0.7.0")
        bootstrap = b"#!/bin/sh\n"
        opener = FakeOpener(
            [
                FakeResponse(json.dumps(payload).encode()),
                FakeResponse(bootstrap, url="https://github.com/release/asset"),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            version, path = release_resolver.resolve_request(
                "latest",
                windows=True,
                destination_dir=Path(temporary),
                opener=opener,
            )
            self.assertEqual(version, "0.7.0")
            self.assertEqual(path.name, "install-0.7.0.ps1")
            self.assertEqual(path.read_bytes(), bootstrap)


class ResolverCommandTests(unittest.TestCase):
    def test_install_command_rejects_non_canonical_repository(self) -> None:
        with mock.patch.object(release_resolver.sys, "stderr"):
            self.assertEqual(
                release_resolver.main(
                    [
                        "install",
                        "--repository",
                        "someone-else/dev-flow-orchestrator",
                        "--requested",
                        "0.6.8",
                    ]
                ),
                1,
            )

    def test_install_command_rejects_source_root_environment(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEV_FLOW_SOURCE_ROOT": "/some/checkout"}
        ):
            self.assertEqual(
                release_resolver.main(
                    [
                        "install",
                        "--repository",
                        release_resolver.CANONICAL_REPOSITORY,
                        "--requested",
                        "latest",
                    ]
                ),
                1,
            )

    def test_install_command_runs_the_acquired_bootstrap_with_forwarded_arguments(self) -> None:
        payload = _release_payload("0.7.0")
        bootstrap = b"#!/bin/sh\nexit 0\n"
        opener = FakeOpener(
            [
                FakeResponse(json.dumps(payload).encode()),
                FakeResponse(bootstrap, url="https://github.com/release/asset"),
            ]
        )
        captured: dict = {}

        def fake_run(*args, **kwargs):
            captured["command"] = list(args[1])
            return 0

        with (
            mock.patch.object(
                release_resolver, "resolve_request", side_effect=lambda *args, **kwargs: ("0.7.0", Path("/tmp/install-0.7.0.sh"))
            ),
            mock.patch.object(release_resolver, "run_version_bootstrap", side_effect=fake_run),
        ):
            self.assertEqual(
                release_resolver.main(
                    [
                        "install",
                        "--repository",
                        release_resolver.CANONICAL_REPOSITORY,
                        "--requested",
                        "latest",
                        "--",
                        "--runtime-root",
                        "/opt/my runtime",
                    ]
                ),
                0,
            )
        self.assertEqual(
            captured["command"],
            ["--runtime-root", "/opt/my runtime"],
        )


if __name__ == "__main__":
    unittest.main()
