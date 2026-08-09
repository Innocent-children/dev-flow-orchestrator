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


def canonical_tool_projection(tools, *, output_schemas=None) -> list:
    """Normalize the complete client-observable tools/list surface."""
    schemas = OUTPUT_SCHEMAS if output_schemas is None else output_schemas
    projected = []
    for tool in tools:
        name = getattr(tool, "name", None)
        parameters = getattr(tool, "parameters", None)
        annotations = getattr(tool, "annotations", None)
        meta = getattr(tool, "meta", None)
        if not isinstance(name, str) or name not in schemas:
            raise ValueError("tool catalog contains an unknown tool")
        annotation_value = (
            annotations.model_dump(by_alias=True, exclude_none=True)
            if hasattr(annotations, "model_dump")
            else annotations
        )
        projected.append({
            "name": name,
            "description": getattr(tool, "description", None),
            "inputSchema": parameters,
            "outputSchema": schemas[name],
            "annotations": annotation_value,
            "execution": {"taskSupport": "forbidden"},
            "meta": meta,
        })
    return sorted(projected, key=lambda item: item["name"].encode("utf-8"))


def catalog_digest(projection: object) -> str:
    if isinstance(projection, (list, tuple)):
        projection = sorted(
            projection,
            key=lambda item: str(item.get("name", "")).encode("utf-8")
            if isinstance(item, dict)
            else b"",
        )
    return _digest(projection)
GUIDANCE_CATALOG_DIGEST = _digest({
    "server_instructions": SERVER_INSTRUCTIONS,
    "catalog": GUIDANCE_CATALOG,
    "independent_review_guidance_digest": INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
})
