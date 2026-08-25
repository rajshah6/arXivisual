"""Base agent class with provider-switchable LLM support (Azure OpenAI / Dedalus)."""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use system env vars


# Default model per provider. For Azure this is the *deployment name* you
# created in Azure AI Foundry (defaults to the model name, e.g. "gpt-5").
DEFAULT_DEDALUS_MODEL = "claude-sonnet-4-5"


def _azure_deployment() -> str:
    return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5")


# GPT-5 reasoning tokens count against max_completion_tokens. Agents size
# max_tokens for the *visible* answer, so give the model extra room to think
# or it can return an empty message after exhausting the cap on reasoning.
_AZURE_REASONING_HEADROOM = 4096


def _detect_provider() -> str:
    """Resolve the LLM provider from env: LLM_PROVIDER wins, else auto-detect."""
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit == "azure":
        _require_azure_env()
        return "azure"
    if explicit == "dedalus":
        _require_dedalus_env()
        return "dedalus"
    if explicit:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={explicit!r}. Use 'azure' or 'dedalus'."
        )

    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.environ.get("DEDALUS_API_KEY"):
        return "dedalus"
    raise RuntimeError(
        "No LLM provider configured. Set AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT "
        "(Azure OpenAI, GPT-5 family) or DEDALUS_API_KEY (Dedalus)."
    )


def _require_azure_env() -> None:
    missing = [
        k for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT")
        if not os.environ.get(k)
    ]
    if missing:
        raise RuntimeError(f"LLM_PROVIDER=azure but missing env vars: {', '.join(missing)}")


def _require_dedalus_env() -> None:
    if not os.environ.get("DEDALUS_API_KEY"):
        raise RuntimeError("LLM_PROVIDER=dedalus but DEDALUS_API_KEY is not set.")


def get_provider() -> str:
    """Get the current provider name (validates env on every call)."""
    return _detect_provider()


# ---------------------------------------------------------------------------
# Azure OpenAI (GPT-5 family) — billed against Azure / Microsoft credits
# ---------------------------------------------------------------------------

_azure_async_client = None
_azure_sync_client = None


def _langfuse_enabled() -> bool:
    """Langfuse tracing is on when both project keys are present in the env."""
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _openai_classes():
    """Return (OpenAI, AsyncOpenAI) classes.

    When Langfuse is configured, return its drop-in wrappers so every LLM call
    is traced automatically (model, token usage, cost, latency). The wrapper
    imports must happen AFTER env vars are loaded — hence the deferred import.
    Falls back to the plain SDK when Langfuse isn't configured (local dev).
    """
    if _langfuse_enabled():
        from langfuse.openai import OpenAI, AsyncOpenAI
    else:
        from openai import OpenAI, AsyncOpenAI
    return OpenAI, AsyncOpenAI


def _azure_base_url() -> str:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    return f"{endpoint}/openai/v1/"


def _get_azure_client():
    global _azure_async_client
    if _azure_async_client is None:
        _, AsyncOpenAI = _openai_classes()
        _azure_async_client = AsyncOpenAI(
            base_url=_azure_base_url(),
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            timeout=300.0,  # 5 min — large paper summarization needs headroom
        )
    return _azure_async_client


def _get_azure_sync_client():
    global _azure_sync_client
    if _azure_sync_client is None:
        OpenAI, _ = _openai_classes()
        _azure_sync_client = OpenAI(
            base_url=_azure_base_url(),
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            timeout=300.0,
        )
    return _azure_sync_client


def _azure_model(model: str | None) -> str:
    """Map a requested model to an Azure deployment name.

    Claude model names (the old Dedalus defaults) map to the configured
    GPT-5 deployment; explicit gpt-* names pass through.
    """
    if not model or model.startswith("claude") or "/" in model:
        return _azure_deployment()
    return model


def _azure_request_kwargs(
    model: str, prompt: str, system_prompt: str, max_tokens: int
) -> dict:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens + _AZURE_REASONING_HEADROOM,
    }
    # minimal | low | medium | high — low keeps the pipeline fast/cheap
    kwargs["reasoning_effort"] = os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "low")
    return kwargs


# ---------------------------------------------------------------------------
# Dedalus (legacy fallback)
# ---------------------------------------------------------------------------

_dedalus_runner = None


def _get_dedalus_runner():
    """Get or create the shared DedalusRunner instance."""
    global _dedalus_runner
    if _dedalus_runner is None:
        from dedalus_labs import AsyncDedalus, DedalusRunner
        client = AsyncDedalus(
            timeout=300.0,  # 5 min — large paper summarization needs headroom
        )
        _dedalus_runner = DedalusRunner(client, verbose=False)
    return _dedalus_runner


def _dedalus_model(model: str) -> str:
    """Convert bare model name to Dedalus format (anthropic/model-name)."""
    if "/" in model:
        return model
    return f"anthropic/{model}"


def _get_client() -> None:
    """Compatibility shim: agents don't hold a direct SDK client."""
    return None


def get_model_name(model: str | None = None) -> str:
    """Get the model name for the active provider."""
    if model:
        return model
    if get_provider() == "azure":
        return _azure_deployment()
    return DEFAULT_DEDALUS_MODEL


# ---------------------------------------------------------------------------
# Standalone LLM call helpers (usable outside BaseAgent, e.g. validators)
# ---------------------------------------------------------------------------

def _with_trace_name(kwargs: dict, name: str | None) -> dict:
    """Attach a Langfuse generation name — only when tracing is on, since the
    plain OpenAI client rejects the unknown ``name`` kwarg."""
    if name and _langfuse_enabled():
        kwargs["name"] = name
    return kwargs


async def call_llm(
    prompt: str,
    model: str | None = None,
    system_prompt: str = "",
    max_tokens: int = 4096,
    name: str | None = None,
) -> str:
    """Async LLM call routed through the configured provider."""
    provider = get_provider()
    input_words = len(prompt.split())
    t0 = time.monotonic()

    if provider == "azure":
        resolved = _azure_model(model)
        logger.info(f"[LLM] Calling azure/{resolved} ({input_words} input words, max_tokens={max_tokens})")
        try:
            client = _get_azure_client()
            resp = await client.chat.completions.create(
                **_with_trace_name(
                    _azure_request_kwargs(resolved, prompt, system_prompt, max_tokens),
                    name,
                )
            )
            output = resp.choices[0].message.content or ""
            elapsed = time.monotonic() - t0
            logger.info(f"[LLM] azure/{resolved} responded in {elapsed:.1f}s ({len(output.split())} output words)")
            return output
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error(f"[LLM] azure/{resolved} FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")
            raise

    dedalus_model = _dedalus_model(model or DEFAULT_DEDALUS_MODEL)
    logger.info(f"[LLM] Calling {dedalus_model} ({input_words} input words, max_tokens={max_tokens})")
    try:
        runner = _get_dedalus_runner()
        result = await runner.run(
            input=prompt,
            model=dedalus_model,
            instructions=system_prompt,
            max_tokens=max_tokens,
        )
        elapsed = time.monotonic() - t0
        output = result.final_output or ""
        logger.info(f"[LLM] {dedalus_model} responded in {elapsed:.1f}s ({len(output.split())} output words)")
        return output
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.error(f"[LLM] {dedalus_model} FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")
        raise


def call_llm_sync(
    prompt: str,
    model: str | None = None,
    system_prompt: str = "",
    max_tokens: int = 4096,
    name: str | None = None,
) -> str:
    """Synchronous LLM call routed through the configured provider."""
    provider = get_provider()

    if provider == "azure":
        resolved = _azure_model(model)
        client = _get_azure_sync_client()
        resp = client.chat.completions.create(
            **_with_trace_name(
                _azure_request_kwargs(resolved, prompt, system_prompt, max_tokens),
                name,
            )
        )
        return resp.choices[0].message.content or ""

    import asyncio

    runner = _get_dedalus_runner()
    result = asyncio.run(runner.run(
        input=prompt,
        model=_dedalus_model(model or DEFAULT_DEDALUS_MODEL),
        instructions=system_prompt,
        max_tokens=max_tokens,
    ))
    return result.final_output or ""


class BaseAgent:
    """
    Base class for all AI agents in the pipeline.

    Provider is selected via env: Azure OpenAI (AZURE_OPENAI_*) or
    Dedalus (DEDALUS_API_KEY). See _detect_provider().
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
        # Readable Langfuse generation name, e.g. "manim_generator"
        self._trace_name = Path(prompt_file).stem

        # Keep self.client for any code that still references it directly
        self.client = _get_client()

        # Log active provider
        if self._provider == "azure":
            print(f"☁️  Azure OpenAI → {_azure_model(self.model)}")
        else:
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
            name=self._trace_name,
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
            name=self._trace_name,
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
