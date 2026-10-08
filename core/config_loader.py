"""
Configuration loader for the Fixora Diagnostic Orchestrator.

Reads the YAML config file and produces validated settings for HolmesGPT,
toolsets, MCP servers, and the FastAPI server.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "holmes_config.yaml"


# ---------------------------------------------------------------------------
# Pydantic models for typed, validated configuration
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    model: str = "ollama_chat/qwen3:4b"
    api_base: Optional[str] = "http://localhost:11434"
    api_key: Optional[str] = None
    max_steps: int = 30
    temperature: float = 0.7
    fast_model: Optional[str] = None


class BuiltinToolsetConfig(BaseModel):
    enabled: bool = False
    env: Dict[str, str] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    description: str = ""
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    llm_instructions: str = ""


class InvestigationConfig(BaseModel):
    system_prompt: str = (
        "You are an expert SRE / DevOps engineer performing root cause analysis. "
        "Always gather evidence from multiple sources before concluding. "
        "Structure your response with: Summary, Evidence, Root Cause, Recommendations."
    )
    timeout: int = 300
    max_tool_calls: int = 50


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8092


class FixoraConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    builtin_toolsets: Dict[str, BuiltinToolsetConfig] = Field(default_factory=dict)
    mcp_servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)
    custom_toolsets: List[str] = Field(default_factory=list)
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ---------------------------------------------------------------------------
# Environment variable interpolation
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\{\{\s*env\.(\w+)\s*\}\}")


def _resolve_env_vars(value: Any) -> Any:
    """Recursively replace {{ env.VAR }} placeholders with os.environ values."""
    if isinstance(value, str):
        def _replacer(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        return _ENV_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[str] = None) -> FixoraConfig:
    """Load and validate the Fixora YAML configuration.

    Args:
        config_path: Path to the YAML config file.
                     Falls back to ``FIXORA_CONFIG_PATH`` env var,
                     then to ``config/holmes_config.yaml``.

    Returns:
        A validated ``FixoraConfig`` instance with env vars resolved.
    """
    path = Path(
        config_path
        or os.environ.get("FIXORA_CONFIG_PATH", "")
        or DEFAULT_CONFIG_PATH
    )

    if not path.exists():
        logger.warning("Config file not found at %s - using defaults", path)
        return FixoraConfig()

    logger.info("Loading config from %s", path)

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    # Strip None values from top-level keys (happens when YAML sections
    # exist but contain only comments, e.g. ``mcp_servers:`` with nothing under it).
    cleaned = {k: v for k, v in raw.items() if v is not None}

    resolved = _resolve_env_vars(cleaned)

    return FixoraConfig(**resolved)


def resolve_toolset_paths(config: FixoraConfig, config_dir: Optional[Path] = None) -> List[str]:
    """Resolve custom toolset file paths relative to the config directory.

    Args:
        config: The loaded configuration.
        config_dir: Base directory for resolving relative paths.
                    Defaults to the ``config/`` directory.

    Returns:
        List of absolute paths to YAML toolset files that exist on disk.
    """
    base = config_dir or (DEFAULT_CONFIG_PATH.parent)
    resolved: List[str] = []

    for toolset_path in config.custom_toolsets:
        full_path = base / toolset_path
        if full_path.exists():
            resolved.append(str(full_path))
            logger.info("Loaded custom toolset: %s", full_path)
        else:
            logger.warning("Custom toolset file not found: %s", full_path)

    return resolved
