"""Base agent class with Anthropic client and prompt loading."""

import json
import os
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use system env vars


# Martian API configuration
MARTIAN_BASE_URL = "https://api.withmartian.com/v1"

# Default models - Kimi K2.5 via Martian for cost savings
DEFAULT_MODEL_ANTHROPIC = "claude-opus-4-5-20251101"  # fallback if no Martian key
DEFAULT_MODEL_MARTIAN = "claude-opus-4-5-20251101"

# Flag to track if we're using Martian
_using_martian = False


def _get_client() -> Anthropic:
    """
    Get the Anthropic client, using Martian if configured.
    
    Priority:
    1. MARTIAN_API_KEY -> Use Martian as proxy
    2. ANTHROPIC_API_KEY -> Use Anthropic directly
    """
    global _using_martian
    martian_key = os.environ.get("MARTIAN_API_KEY")
    
    if martian_key:
        _using_martian = True
        # Use Martian as proxy to Anthropic
        return Anthropic(
            api_key=martian_key,
            base_url=MARTIAN_BASE_URL,
        )
    else:
        _using_martian = False
        # Use Anthropic directly (will read ANTHROPIC_API_KEY automatically)
        return Anthropic()


def get_model_name(model: str | None = None) -> str:
    """
    Get the correct model name based on which API we're using.

    Martian requires provider-prefixed names: "moonshotai/kimi-k2.5"
    Anthropic requires bare names: "claude-opus-4-5-20251101"
    """
    if model is None:
        return DEFAULT_MODEL_MARTIAN if _using_martian else DEFAULT_MODEL_ANTHROPIC

    if _using_martian:
        # Martian models already have provider/ prefix — pass through as-is
        return model
    else:
        # Remove provider/ prefix for direct Anthropic API
        if "/" in model:
            return model.split("/", 1)[1]
        return model


class BaseAgent:
    """
    Base class for all AI agents in the pipeline.
    
    Provides:
    - Anthropic client initialization (supports Martian proxy)
    - System prompt loading (Manim reference)
    - User prompt template loading
    - JSON response parsing
    
    Environment Variables:
    - MARTIAN_API_KEY: If set, uses Martian as proxy (recommended for unlimited usage)
    - ANTHROPIC_API_KEY: Direct Anthropic access (fallback)
    
    Model Names:
    - For Martian: "moonshotai/kimi-k2.5" (or any provider/model format)
    - For Anthropic: "claude-opus-4-5-20251101" (bare model name)
    - The code auto-converts between formats based on which API is used
    """
    
    def __init__(
        self,
        prompt_file: str,
        model: str | None = None,
        max_tokens: int = 4096,
    ):
        """
        Initialize the agent.
        
        Args:
            prompt_file: Name of the prompt template file in prompts/
            model: Model to use. If None, uses default. Auto-converts format for Martian/Anthropic.
            max_tokens: Maximum tokens in response
        """
        self.client = _get_client()
        self.model = get_model_name(model)
        self.max_tokens = max_tokens
        self.system_prompt = self._load_system_prompt()
        self.prompt_template = self._load_prompt(prompt_file)
        
        # Log which API is being used (only once per agent type)
        if _using_martian:
            print(f"🚀 Martian API → {self.model}")
        else:
            print(f"🔑 Anthropic API → {self.model}")
    
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
    
    async def run(self, **kwargs: Any) -> dict:
        """
        Run the agent with the given parameters.
        
        This method should be overridden by subclasses for specific behavior.
        Default implementation formats the prompt and returns parsed JSON.
        
        Args:
            **kwargs: Variables to format into the prompt template
            
        Returns:
            Parsed JSON response as a dictionary
        """
        prompt = self._format_prompt(**kwargs)
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return self._parse_json_response(response.content[0].text)
    
    def run_sync(self, **kwargs: Any) -> dict:
        """Synchronous version of run() for testing."""
        prompt = self._format_prompt(**kwargs)
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return self._parse_json_response(response.content[0].text)
