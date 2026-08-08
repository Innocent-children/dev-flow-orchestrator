"""Deterministic MCP catalog and guidance digests."""

import hashlib
import json

from .guidance import GUIDANCE_CATALOG, SERVER_INSTRUCTIONS
from ..review_guidance import INDEPENDENT_REVIEW_GUIDANCE_DIGEST
from .schemas import OUTPUT_SCHEMAS


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


TOOL_NAMES = tuple(sorted(OUTPUT_SCHEMAS))
TOOL_CATALOG_DIGEST = _digest({"names": TOOL_NAMES, "output_schemas": OUTPUT_SCHEMAS})
GUIDANCE_CATALOG_DIGEST = _digest({
    "server_instructions": SERVER_INSTRUCTIONS,
    "catalog": GUIDANCE_CATALOG,
    "independent_review_guidance_digest": INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
})
