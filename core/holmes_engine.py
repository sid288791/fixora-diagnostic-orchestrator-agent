"""
HolmesGPT RCA Engine - wraps the HolmesGPT Python SDK.

Responsibilities:
  - Translate FixoraConfig into a HolmesGPT ``Config`` instance
  - Bootstrap toolsets (built-in, custom YAML, MCP servers)
  - Expose ``investigate()`` and ``ask()`` for the FastAPI layer

HolmesGPT modules are imported lazily inside ``initialize()`` so that
environment variables required by HolmesGPT (e.g. ``OLLAMA_API_BASE``,
``DISABLE_PROMETHEUS_TOOLSET``) and by individual toolsets can be set
from the YAML config *before* the ``holmes`` package reads them at
import time.
"""

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.config_loader import FixoraConfig, load_config, resolve_toolset_paths

logger = logging.getLogger(__name__)

# HolmesGPT's `prometrix` dependency uses pydantic-v1 internals that break
# on Python >= 3.14.  Disable the built-in Prometheus toolset on affected
# interpreters (the env var is read when holmes.common.env_vars is imported).
_NEEDS_PROMETHEUS_DISABLED = sys.version_info >= (3, 14)


# ---------------------------------------------------------------------------
# Data classes for investigation results
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """Record of a single tool invocation during investigation."""
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""


@dataclass
class InvestigationResult:
    """Structured output of an RCA investigation."""
    question: str
    analysis: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    status: str = "completed"  # completed | error | timeout
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class HolmesEngine:
    """Manages the HolmesGPT lifecycle and exposes investigation methods."""

    def __init__(self, config: Optional[FixoraConfig] = None):
        self._fixora_config = config or load_config()
        self._holmes_config: Optional[Any] = None  # holmes.config.Config
        self._initialized = False

    # -- Initialisation -----------------------------------------------------

    def initialize(self) -> None:
        """Build the HolmesGPT Config and pre-load toolsets."""
        cfg = self._fixora_config

        # -- Set env vars BEFORE importing holmes modules ------------------
        # HolmesGPT reads several env vars at import time (env_vars.py),
        # so they must be set before `holmes.*` is imported.

        # Ollama endpoint used by LiteLLM
        if cfg.llm.api_base:
            os.environ.setdefault("OLLAMA_API_BASE", cfg.llm.api_base)

        # Disable the Prometheus toolset on interpreters where its
        # pydantic-v1 dependency (prometrix) is broken.
        if _NEEDS_PROMETHEUS_DISABLED:
            os.environ.setdefault("DISABLE_PROMETHEUS_TOOLSET", "true")
            logger.info(
                "Python %s detected - disabled Prometheus toolset "
                "(prometrix is incompatible with pydantic-v1 on Python 3.14+)",
                sys.version.split()[0],
            )

        # Per-toolset env vars from YAML config
        for _name, ts in cfg.builtin_toolsets.items():
            if ts.enabled:
                for env_key, env_val in ts.env.items():
                    if env_val:
                        os.environ.setdefault(env_key, env_val)

        # -- Lazy holmes imports -------------------------------------------
        from holmes.config import Config as HolmesConfig

        # Resolve custom toolset YAML paths
        custom_toolset_paths = resolve_toolset_paths(cfg)

        # Build the HolmesGPT Config object
        holmes_kwargs: Dict[str, Any] = {
            "model": cfg.llm.model,
            "max_steps": cfg.llm.max_steps,
        }

        if cfg.llm.api_key:
            holmes_kwargs["api_key"] = cfg.llm.api_key
        if cfg.llm.api_base:
            holmes_kwargs["api_base"] = cfg.llm.api_base
        if cfg.llm.fast_model:
            holmes_kwargs["fast_model"] = cfg.llm.fast_model
        if custom_toolset_paths:
            holmes_kwargs["custom_toolsets"] = custom_toolset_paths

        self._holmes_config = HolmesConfig(**holmes_kwargs)

        self._initialized = True
        logger.info(
            "HolmesEngine initialized: model=%s, custom_toolsets=%d, mcp_servers=%d",
            cfg.llm.model,
            len(custom_toolset_paths),
            len([m for m in cfg.mcp_servers.values() if m.enabled]),
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    # -- Public API ---------------------------------------------------------

    def get_toolsets_info(self) -> List[Dict[str, Any]]:
        """Return metadata about all loaded toolsets (for the /toolsets endpoint)."""
        self._ensure_initialized()
        assert self._holmes_config is not None

        from holmes.core.tools import ToolsetTag

        ai = self._holmes_config.create_toolcalling_llm(
            toolset_tag_filter=[ToolsetTag.CORE, ToolsetTag.CLI],
            enable_all_toolsets_possible=True,
        )

        results = []
        for ts in ai.tool_executor.toolsets:
            results.append({
                "name": ts.name,
                "description": getattr(ts, "description", ""),
                "status": str(getattr(ts, "status", "unknown")),
                "type": str(getattr(ts, "toolset_type", "unknown")),
                "tools": [t.name for t in ts.tools] if hasattr(ts, "tools") else [],
            })
        return results

    async def investigate(self, question: str, context: Optional[Dict[str, Any]] = None) -> InvestigationResult:
        """Run a full RCA investigation using HolmesGPT's agentic loop.

        Args:
            question: The diagnostic question or incident description.
            context: Optional additional context (e.g., alert payload, service name).

        Returns:
            An ``InvestigationResult`` with the analysis and tool call log.
        """
        self._ensure_initialized()
        assert self._holmes_config is not None

        # Build the prompt
        prompt = question
        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            prompt = f"{question}\n\nAdditional context:\n{context_str}"

        system_additions = self._fixora_config.investigation.system_prompt

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._run_investigation, prompt, system_additions
                ),
                timeout=self._fixora_config.investigation.timeout,
            )
            return result
        except asyncio.TimeoutError:
            return InvestigationResult(
                question=question,
                analysis="",
                status="timeout",
                error=f"Investigation exceeded timeout of "
                      f"{self._fixora_config.investigation.timeout}s",
            )
        except Exception as e:
            logger.exception("Investigation failed: %s", e)
            return InvestigationResult(
                question=question,
                analysis="",
                status="error",
                error=str(e),
            )

    async def ask(self, question: str) -> InvestigationResult:
        """Ask a simple question (no structured investigation context)."""
        return await self.investigate(question)

    # -- Internal -----------------------------------------------------------

    def _run_investigation(self, prompt: str, system_prompt_additions: str) -> InvestigationResult:
        """Synchronous wrapper that runs the HolmesGPT agentic loop."""
        assert self._holmes_config is not None

        from holmes.core.prompt import build_initial_ask_messages
        from holmes.core.tools import ToolsetTag

        ai = self._holmes_config.create_toolcalling_llm(
            toolset_tag_filter=[ToolsetTag.CORE, ToolsetTag.CLI],
            enable_all_toolsets_possible=True,
        )

        messages = build_initial_ask_messages(
            initial_user_prompt=prompt,
            file_paths=None,
            tool_executor=ai.tool_executor,
            skills=self._holmes_config.get_skill_catalog(),
            system_prompt_additions=system_prompt_additions,
        )

        response = ai.call(messages)

        # Extract tool calls from the conversation (LLMResult.tool_calls
        # is a list of ToolCallResult: tool_name, description, result).
        tool_calls: List[ToolCall] = []
        for tc in response.tool_calls or []:
            tool_calls.append(ToolCall(
                tool_name=tc.tool_name,
                result_summary=(tc.description or "")[:500],
            ))

        return InvestigationResult(
            question=prompt,
            analysis=response.result or "",
            tool_calls=tool_calls,
            status="completed",
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[HolmesEngine] = None


def get_engine() -> HolmesEngine:
    """Return the singleton HolmesEngine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = HolmesEngine()
    return _engine
