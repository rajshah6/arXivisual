"""Dedalus-powered base agent with multi-model handoff support.

This class enables the "Best Use of Dedalus API" prize by using multiple
models in the same agent via the Dedalus SDK's handoff feature.

Usage:
    class MyAgent(DedalusBaseAgent):
        def __init__(self):
            super().__init__(
                prompt_file="my_prompt.md",
                task_type="code",  # Uses code-optimized model chain
            )
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


# Task types that map to different model chains for handoffs
TaskType = Literal["research", "code", "creative", "analysis", "multi_step"]

# Model chains using ONLY Claude models for handoffs
# Dedalus SDK automatically routes work between models based on task complexity
MODEL_CHAINS: dict[TaskType, list[str]] = {
    # Research: Haiku quickly gathers → Sonnet analyzes → Opus synthesizes
    "research": [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-5"
    ],

    # Code generation: Sonnet plans architecture → Opus implements
    "code": [
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-5"
    ],

    # Creative writing: Opus handles everything (best for nuanced content)
    "creative": ["anthropic/claude-opus-4-5"],

    # Analysis: Haiku for quick scan → Opus for deep reasoning
    "analysis": [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-opus-4-5"
    ],

    # Multi-step complex tasks: Full handoff chain
    "multi_step": [
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-opus-4-5"
    ],
}


class DedalusBaseAgent:
    """
    Base class for AI agents using Dedalus SDK with Claude model handoffs.

    🔄 Handoff Workflow (Simple & Automatic)
    ----------------------------------------
    1. You provide a list of Claude models (Haiku, Sonnet, Opus)
    2. Dedalus SDK automatically routes subtasks to the right model
    3. Faster models handle simple parts, Opus handles complex reasoning

    Example Handoff Chains:
    - Research: Haiku gathers → Sonnet analyzes → Opus synthesizes
    - Code: Sonnet plans → Opus implements
    - Creative: Opus handles everything

    Why This Works:
    - Cost efficient: Use Haiku/Sonnet for 80% of work
    - Quality: Opus handles the hard parts
    - Speed: Parallel processing when possible

    Environment Variables:
    - DEDALUS_API_KEY: Required. Get from https://www.dedaluslabs.ai/dashboard/api-keys

    Example:
        class ManimGenerator(DedalusBaseAgent):
            def __init__(self):
                super().__init__(
                    prompt_file="manim_generator.md",
                    task_type="code",  # Sonnet → Opus handoff
                )
    """
    
    def __init__(
        self,
        prompt_file: str,
        task_type: TaskType = "research",
        custom_models: list[str] | None = None,
        max_tokens: int = 4096,
        mcp_servers: list[str] | None = None,
    ):
        """
        Initialize the Dedalus-powered agent.
        
        Args:
            prompt_file: Name of the prompt template file in prompts/
            task_type: Type of task - determines which model chain to use for handoffs
            custom_models: Override the default model chain with specific models
            max_tokens: Maximum tokens in response
            mcp_servers: Optional MCP servers to connect (e.g., ["windsornguyen/arxiv-mcp"])
        """
        # Lazy import to avoid breaking if dedalus_labs not installed
        try:
            from dedalus_labs import AsyncDedalus, DedalusRunner
        except ImportError:
            raise ImportError(
                "Dedalus SDK not installed. Run: uv pip install dedalus_labs\n"
                "Then set DEDALUS_API_KEY in your environment."
            )
        
        self.client = AsyncDedalus()
        self.runner = DedalusRunner(self.client)
        self.task_type = task_type
        self.max_tokens = max_tokens
        self.mcp_servers = mcp_servers or []
        
        # Set up model chain for handoffs
        self.models = custom_models or MODEL_CHAINS.get(task_type, MODEL_CHAINS["research"])

        # Load prompts
        self.system_prompt = self._load_system_prompt()
        self.prompt_template = self._load_prompt(prompt_file)

        # Show the handoff chain being used
        model_names = [m.split("/")[-1] for m in self.models]  # Clean names
        print(f"🔄 Dedalus Handoffs ({task_type}): {' → '.join(model_names)}")
    
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
        """
        result = self.prompt_template
        
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
        json_patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, content)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from response: {e}\nContent: {content[:500]}")
    
    def _extract_code_block(self, content: str, language: str = "python") -> str:
        """Extract code from a markdown code block."""
        pattern = rf"```{language}\s*([\s\S]*?)\s*```"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
        
        pattern = r"```\s*([\s\S]*?)\s*```"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
        
        return content.strip()
    
    async def run(self, **kwargs: Any) -> dict:
        """
        Run the agent with automatic Claude model handoffs.

        Simple Workflow:
        1. Format the prompt with your variables
        2. Pass the prompt + list of Claude models to Dedalus
        3. Dedalus automatically routes work across models
        4. Get back the final result

        Args:
            **kwargs: Variables to format into the prompt template

        Returns:
            Parsed JSON response as a dictionary
        """
        # Step 1: Prepare the input
        prompt = self._format_prompt(**kwargs)
        if self.system_prompt:
            prompt = f"<system>\n{self.system_prompt}\n</system>\n\n{prompt}"

        # Step 2: Run with handoffs (Dedalus handles the routing automatically!)
        # Just pass a list of models - that's it!
        result = await self.runner.run(
            input=prompt,
            model=self.models,  # 🔄 Handoff magic: Dedalus routes across these models
            mcp_servers=self.mcp_servers or None,
        )

        # Step 3: Parse and return
        return self._parse_json_response(result.final_output)
    
    async def run_raw(self, **kwargs: Any) -> str:
        """
        Run with handoffs and return raw text (not JSON).

        Same handoff workflow as run(), but returns the raw output.
        Useful for code generation or creative writing.
        """
        prompt = self._format_prompt(**kwargs)
        if self.system_prompt:
            prompt = f"<system>\n{self.system_prompt}\n</system>\n\n{prompt}"

        # 🔄 Handoff across Claude models
        result = await self.runner.run(
            input=prompt,
            model=self.models,
            mcp_servers=self.mcp_servers or None,
        )

        return result.final_output

    async def run_code(self, **kwargs: Any) -> str:
        """
        Run with handoffs and extract code from response.

        Convenience method for code generation with handoffs.
        """
        raw_output = await self.run_raw(**kwargs)
        return self._extract_code_block(raw_output)
    
    def run_sync(self, **kwargs: Any) -> dict:
        """Synchronous version of run() for testing."""
        import asyncio
        return asyncio.run(self.run(**kwargs))


# Convenience subclasses for common patterns

class ResearchAgent(DedalusBaseAgent):
    """Agent optimized for research and information gathering."""
    
    def __init__(self, prompt_file: str, **kwargs):
        super().__init__(prompt_file, task_type="research", **kwargs)


class CodeAgent(DedalusBaseAgent):
    """Agent optimized for code generation with Claude + Codex handoff."""
    
    def __init__(self, prompt_file: str, **kwargs):
        super().__init__(prompt_file, task_type="code", **kwargs)


class CreativeAgent(DedalusBaseAgent):
    """Agent optimized for creative writing and educational content."""
    
    def __init__(self, prompt_file: str, **kwargs):
        super().__init__(prompt_file, task_type="creative", **kwargs)


class AnalysisAgent(DedalusBaseAgent):
    """Agent optimized for complex analysis with reasoning model handoff."""
    
    def __init__(self, prompt_file: str, **kwargs):
        super().__init__(prompt_file, task_type="analysis", **kwargs)
