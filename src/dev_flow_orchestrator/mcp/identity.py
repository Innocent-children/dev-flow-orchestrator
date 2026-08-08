"""Non-persisted MCP interface identities."""

from .._version import RELEASE_VERSION
from ..product import MODEL_VERSION


SERVER_NAME = "dev-flow"
MCP_INTERFACE_SCHEMA = "dev-flow-mcp/1.0.0"
MCP_RESULT_SCHEMA = "dev-flow-mcp-result/1.0.0"
MCP_ACTION_SCHEMA = "dev-flow-mcp-action/1.0.0"
MCP_GUIDANCE_SCHEMA = "dev-flow-mcp-guidance/1.0.0"
SUPPORTED_PYTHON = ">=3.10,<3.15"

# Model-facing context limits are interface properties, not persisted-model
# identities.  Adapters import one authority rather than repeating byte budgets.
MCP_AUTHORITY_PREFIX_MAX_BYTES = 512
MCP_SERVER_INSTRUCTIONS_MAX_BYTES = 4 * 1024
MCP_GUIDANCE_MAX_BYTES = 8 * 1024
MCP_CURRENT_ACTION_MAX_BYTES = 128 * 1024


def interface_identity() -> dict:
    return {
        "server": SERVER_NAME,
        "release_version": RELEASE_VERSION,
        "model_version": MODEL_VERSION,
        "interface_schema": MCP_INTERFACE_SCHEMA,
        "result_schema": MCP_RESULT_SCHEMA,
        "action_schema": MCP_ACTION_SCHEMA,
        "guidance_schema": MCP_GUIDANCE_SCHEMA,
    }
