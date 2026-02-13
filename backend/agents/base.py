"""Base agent class with Dedalus-only LLM support."""

import json
import os
import re
from pathlib import Path
from typing import Any

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use system env vars


# Default model
DEFAULT_MODEL = "claude-opus-4-5-20251101"

# Provider is intentionally fixed to Dedalus for production consistency.
_provider: str = "dedalus"

# Shared Dedalus runner (reuse across agents to avoid re-init)
_dedalus_runner = None


def _detect_provider() -> str:
    """Detect provider and enforce Dedalus-only configuration."""
    if not os.environ.get("DEDALUS_API_KEY"):
        raise RuntimeError(
            "DEDALUS_API_KEY is required. This project is configured to use "
            "Dedalus-only LLM routing."
        )
    return "dedalus"


def get_provider() -> str:
    """Get the current provider name."""
    # Always validate env when requested so misconfigurations fail fast.
    _detect_provider()
    return _provider


def _get_dedalus_runner():
    """Get or create the shared DedalusRunner instance."""
    global _dedalus_runner
    if _dedalus_runner is None:
        from dedalus_labs import AsyncDedalus, DedalusRunner
        client = AsyncDedalus()
        _dedalus_runner = DedalusRunner(client, verbose=False)
    return _dedalus_runner


def _dedalus_model(model: str) -> str:
    """Convert bare model name to Dedalus format (anthropic/model-name)."""
    if "/" in model:
        return model
    return f"anthropic/{model}"


def _get_client() -> None:
    """Compatibility shim: there is no direct SDK client in Dedalus-only mode."""
    return None


def get_model_name(model: str | None = None) -> str:
    """Get the model name (bare name, no provider prefix)."""
    return model or DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Standalone LLM call helpers (usable outside BaseAgent, e.g. validators)
# ---------------------------------------------------------------------------

async def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = "",
    max_tokens: int = 4096,
) -> str:
    """Async LLM call routed through Dedalus."""
    get_provider()
    runner = _get_dedalus_runner()
    result = await runner.run(
        input=prompt,
        model=_dedalus_model(model),
        instructions=system_prompt,
        max_tokens=max_tokens,
    )
    return result.final_output or ""


def call_llm_sync(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = "",
    max_tokens: int = 4096,
) -> str:
    """Synchronous LLM call routed through Dedalus."""
    import asyncio

    get_provider()
    runner = _get_dedalus_runner()
    result = asyncio.run(runner.run(
        input=prompt,
        model=_dedalus_model(model),
        instructions=system_prompt,
        max_tokens=max_tokens,
    ))
    return result.final_output or ""


class BaseAgent:
    """
    Base class for all AI agents in the pipeline.

    Uses Dedalus SDK only (DEDALUS_API_KEY).
    """

    def __init__(
        self,
        prompt_file: str,
        model: str | None = None,
        max_tokens: int = 4096,
    ):
        self._provider = get_provider()
        self.model = get_model_name(model)
        self.max_tokens = max_tokens
        self.system_prompt = self._load_system_prompt()
        self.prompt_template = self._load_prompt(prompt_file)

        # Keep self.client for any code that still references it directly
        self.client = _get_client()

        # Log active provider
        print(f"🔮 Dedalus SDK → anthropic/{self.model}")

    def _get_prompts_dir(self) -> Path:
        """Get the prompts directory path."""
        return Path(__file__).parent.parent / "prompts"

    def _load_system_prompt(self) -> str:
        """Load the curated Manim reference as system prompt."""
        path = self._get_prompts_dir() / "system" / "manim_reference.md"
        if path.exists():
            return path.read_text()
        return ""

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt template file."""
        path = self._get_prompts_dir() / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text()

    def _format_prompt(self, **kwargs: Any) -> str:
        """
        Format the prompt template with provided variables.

        Uses str.replace() instead of str.format() to avoid issues with
        content containing curly braces (like LaTeX's \\begin{pmatrix}).
        Also handles {{ and }} escape sequences like str.format() does.
        """
        result = self.prompt_template

        # Replace all placeholders first
        for key, value in kwargs.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, str(value))

        # Convert escaped braces ({{ -> {, }} -> }) like str.format() does
        result = result.replace("{{", "{").replace("}}", "}")

        return result

    def _parse_json_response(self, content: str) -> dict:
        """
        Extract and parse JSON from the response.

        Handles both raw JSON and JSON wrapped in markdown code blocks.
        """
        # Try to extract JSON from markdown code blocks
        json_patterns = [
            r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
            r"```\s*([\s\S]*?)\s*```",       # ``` ... ```
        ]

        for pattern in json_patterns:
            match = re.search(pattern, content)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # Try parsing the whole content as JSON
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from response: {e}\nContent: {content[:500]}")

    def _extract_code_block(self, content: str, language: str = "python") -> str:
        """
        Extract code from a markdown code block.

        Args:
            content: Response content
            language: Language tag to look for

        Returns:
            Extracted code or empty string
        """
        # Try language-specific block first
        pattern = rf"```{language}\s*([\s\S]*?)\s*```"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()

        # Try generic code block
        pattern = r"```\s*([\s\S]*?)\s*```"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()

        # Return content as-is if no code blocks found
        return content.strip()

    # ------------------------------------------------------------------
    # LLM call helpers — route to the active provider
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Call the LLM via the configured provider (async)."""
        return await call_llm(
            prompt=prompt,
            model=self.model,
            system_prompt=system_prompt or self.system_prompt,
            max_tokens=max_tokens or self.max_tokens,
        )

    def _call_llm_sync(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Call the LLM via the configured provider (sync)."""
        return call_llm_sync(
            prompt=prompt,
            model=self.model,
            system_prompt=system_prompt or self.system_prompt,
            max_tokens=max_tokens or self.max_tokens,
        )

    # ------------------------------------------------------------------
    # Default run methods
    # ------------------------------------------------------------------

    async def run(self, **kwargs: Any) -> dict:
        """
        Run the agent with the given parameters.

        This method should be overridden by subclasses for specific behavior.
        Default implementation formats the prompt and returns parsed JSON.
        """
        prompt = self._format_prompt(**kwargs)
        text = await self._call_llm(prompt)
        return self._parse_json_response(text)

    def run_sync(self, **kwargs: Any) -> dict:
        """Synchronous version of run() for testing."""
        prompt = self._format_prompt(**kwargs)
        text = self._call_llm_sync(prompt)
        return self._parse_json_response(text)
