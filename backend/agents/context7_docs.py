"""
Context7 Documentation Fetcher via Dedalus SDK + MCP Gateway.

Uses the official Dedalus SDK with native MCP server support to connect
to Context7 for live, up-to-date Manim documentation retrieval.

Flow:
  1. DedalusRunner.run() with mcp_servers=["tsion/context7"]
  2. The runner orchestrates Context7 MCP tool calls automatically
  3. Returns structured Manim documentation for the ManimGenerator

Sponsor Track: Dedalus "Best use of tool calling"
  - Uses official Dedalus SDK (AsyncDedalus + DedalusRunner)
  - Context7 MCP via one-line mcp_servers integration
  - Local tools combined with MCP servers
"""

import ast
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEDALUS_API_KEY = os.environ.get("DEDALUS_API_KEY")

# Context7 REST API (direct fallback)
CONTEXT7_API_BASE = "https://context7.com/api/v2"

# Manim library identifier on Context7
MANIM_LIBRARY_NAME = "manim community"

# Cache for fetched docs to avoid redundant API calls within a pipeline run
_docs_cache: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Local tool functions (passed alongside MCP servers to showcase combined
# tool calling for the Dedalus hackathon track)
# ---------------------------------------------------------------------------

def validate_manim_imports(code: str) -> str:
    """Validate that Manim code has correct imports and no disallowed modules.

    Checks for:
    - Presence of 'from manim import *'
    - No dangerous imports (os.system, subprocess, etc.)
    - Valid Python syntax

    Args:
        code: The Manim Python source code to validate.

    Returns:
        A JSON string with validation results: {"valid": bool, "issues": list[str]}
    """
    issues: list[str] = []

    # Check for manim import
    if "from manim import" not in code and "import manim" not in code:
        issues.append("Missing manim import: add 'from manim import *'")

    # Check for dangerous imports
    dangerous = ["os.system", "subprocess", "shutil.rmtree", "eval(", "exec("]
    for pattern in dangerous:
        if pattern in code:
            issues.append(f"Disallowed pattern found: {pattern}")

    # Check for valid Python syntax
    try:
        ast.parse(code)
    except SyntaxError as e:
        issues.append(f"Syntax error at line {e.lineno}: {e.msg}")

    return json.dumps({"valid": len(issues) == 0, "issues": issues})


def check_spatial_bounds(code: str) -> str:
    """Check that Manim objects stay within the visible frame bounds.

    Analyzes position coordinates in the code to detect potential
    off-screen elements.

    Args:
        code: The Manim Python source code to check.

    Returns:
        A JSON string with spatial check results:
        {"in_bounds": bool, "warnings": list[str]}
    """
    warnings: list[str] = []

    # Manim default frame: x in [-7.1, 7.1], y in [-4, 4]
    MAX_X = 7.1
    MAX_Y = 4.0

    # Check for explicit coordinate values (x, y pairs)
    xy_patterns = [
        (r"\.move_to\(\s*\[?\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", "move_to"),
        (r"Dot\(\s*\[?\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", "Dot position"),
    ]

    for pattern, label in xy_patterns:
        for match in re.finditer(pattern, code):
            groups = match.groups()
            if len(groups) >= 2:
                try:
                    x, y = float(groups[0]), float(groups[1])
                    if abs(x) > MAX_X:
                        warnings.append(
                            f"{label}: x={x} exceeds frame width ({MAX_X})"
                        )
                    if abs(y) > MAX_Y:
                        warnings.append(
                            f"{label}: y={y} exceeds frame height ({MAX_Y})"
                        )
                except ValueError:
                    pass

    # Check for single-axis shifts (RIGHT, LEFT, UP, DOWN)
    shift_pattern = r"\.shift\(\s*(RIGHT|LEFT|UP|DOWN)\s*\*\s*(-?[\d.]+)"
    for match in re.finditer(shift_pattern, code):
        direction, value_str = match.groups()
        try:
            value = float(value_str)
            # Map direction to axis
            if direction in ("RIGHT", "LEFT"):
                # x-axis
                if abs(value) > MAX_X:
                    warnings.append(
                        f"shift: {direction}*{value} exceeds frame width ({MAX_X})"
                    )
            elif direction in ("UP", "DOWN"):
                # y-axis
                if abs(value) > MAX_Y:
                    warnings.append(
                        f"shift: {direction}*{value} exceeds frame height ({MAX_Y})"
                    )
        except ValueError:
            pass

    return json.dumps({
        "in_bounds": len(warnings) == 0,
        "warnings": warnings,
    })


def extract_scene_metadata(code: str) -> str:
    """Extract metadata from Manim scene code for validation.

    Extracts the scene class name, base class, animation count,
    and voiceover block count.

    Args:
        code: The Manim Python source code to analyze.

    Returns:
        A JSON string with scene metadata:
        {"class_name": str, "base_class": str, "animation_count": int,
         "voiceover_blocks": int, "has_construct": bool}
    """
    class_match = re.search(
        r"class\s+(\w+)\s*\(\s*(Scene|ThreeDScene|VoiceoverScene)\s*\)",
        code,
    )
    class_name = class_match.group(1) if class_match else "Unknown"
    base_class = class_match.group(2) if class_match else "Unknown"

    animation_count = len(re.findall(
        r"self\.play\(|self\.wait\(|self\.add\(",
        code,
    ))

    voiceover_blocks = len(re.findall(
        r"with\s+self\.voiceover\s*\(",
        code,
    ))

    has_construct = "def construct(self)" in code

    return json.dumps({
        "class_name": class_name,
        "base_class": base_class,
        "animation_count": animation_count,
        "voiceover_blocks": voiceover_blocks,
        "has_construct": has_construct,
    })


# All local tools that can be passed to DedalusRunner alongside MCP servers
LOCAL_TOOLS = [validate_manim_imports, check_spatial_bounds, extract_scene_metadata]


# ---------------------------------------------------------------------------
# Dedalus SDK integration (official SDK with native MCP support)
# ---------------------------------------------------------------------------

async def fetch_manim_docs_via_dedalus(
    query: str = "animations mobjects Scene ThreeDScene",
    max_tokens: int = 5000,
) -> str:
    """
    Fetch live Manim documentation using the Dedalus SDK with Context7 MCP.

    This uses the official Dedalus Python SDK (AsyncDedalus + DedalusRunner)
    with native MCP server support. The Context7 MCP server is connected via
    a single line: mcp_servers=["tsion/context7"].

    The runner automatically:
    - Discovers Context7's tools (resolve-library-id, get-library-docs)
    - Orchestrates the tool calls via the model
    - Returns the final documentation output

    Hackathon Track: Dedalus "Best use of tool calling"
      - Official SDK, not raw API
      - MCP server integration (tsion/context7)
      - Combined with local tools for validation

    Args:
        query: What aspect of Manim to look up
        max_tokens: Max documentation tokens to return

    Returns:
        Formatted documentation string, or empty string on failure
    """
    cache_key = f"dedalus:manim:{query}:{max_tokens}"
    if cache_key in _docs_cache:
        logger.info("Context7 docs cache hit for query: %s", query)
        return _docs_cache[cache_key]

    logger.info("=" * 50)
    logger.info("DEDALUS SDK + CONTEXT7 MCP: Fetching live Manim docs")
    logger.info("  Query: %s", query)
    logger.info("  Max tokens: %s", max_tokens)

    try:
        from dedalus_labs import AsyncDedalus, DedalusRunner

        # AsyncDedalus reads DEDALUS_API_KEY from env automatically
        client = AsyncDedalus()
        runner = DedalusRunner(client, verbose=False)

        result = await runner.run(
            input=(
                f"Fetch the latest Manim Community Edition documentation about: {query}. "
                f"Use the Context7 MCP tools to: "
                f"1. First resolve the library ID for 'manim community' "
                f"2. Then fetch documentation with max {max_tokens} tokens "
                f"Return ONLY the raw documentation text from the tool, no extra commentary."
            ),
            model="anthropic/claude-3-5-haiku-latest",
            mcp_servers=["tsion/context7"],  # One-line MCP connection!
            instructions=(
                "You are a documentation retrieval assistant. "
                "Use the Context7 MCP tools to fetch current Manim library documentation. "
                "First call resolve-library-id with 'manim community', "
                "then call get-library-docs with the returned ID and the user's query. "
                "Return ONLY the raw documentation text, no extra commentary."
            ),
            max_tokens=max_tokens,
            max_steps=6,
        )

        result_text = result.final_output or ""

        if result_text and len(result_text) > 100:
            logger.info(
                "  Fetched %d chars of live Manim docs via Dedalus SDK + Context7 MCP",
                len(result_text),
            )

            # Log MCP tool usage for hackathon demonstration
            if result.tools_called:
                logger.info("  Tools called: %s", result.tools_called)
            if result.mcp_results:
                logger.info("  MCP results: %d", len(result.mcp_results))
            logger.info("  Steps used: %d", result.steps_used)

            _docs_cache[cache_key] = result_text
            return result_text
        else:
            logger.warning("  Dedalus SDK returned short/empty response, falling back")
            return ""

    except ImportError:
        logger.error("  dedalus-labs package not installed, falling back to direct Context7")
        return ""
    except Exception as exc:
        logger.error("  Dedalus SDK + Context7 MCP failed: %s", exc)
        logger.info("  Falling back to direct Context7 API")
        return ""


async def fetch_manim_docs_via_dedalus_with_tools(
    query: str = "animations mobjects Scene ThreeDScene",
    max_tokens: int = 5000,
    manim_code: str = "",
) -> str:
    """
    Fetch Manim docs AND validate code using Dedalus SDK with both
    MCP servers and local tools combined.

    This showcases the Dedalus SDK's ability to use MCP servers (Context7)
    alongside local Python tool functions in a single runner.run() call.

    Args:
        query: What aspect of Manim to look up
        max_tokens: Max documentation tokens
        manim_code: Optional Manim code to validate alongside doc fetch

    Returns:
        Documentation + validation results as a string
    """
    cache_key = f"dedalus_tools:manim:{query}:{max_tokens}"
    if not manim_code and cache_key in _docs_cache:
        logger.info("Context7 docs+tools cache hit for query: %s", query)
        return _docs_cache[cache_key]

    logger.info("DEDALUS SDK: Fetching docs + running local tools")

    try:
        from dedalus_labs import AsyncDedalus, DedalusRunner

        client = AsyncDedalus()
        runner = DedalusRunner(client, verbose=False)

        input_text = (
            f"Fetch the latest Manim Community Edition documentation about: {query}. "
            f"Use the Context7 MCP tools to resolve the library and fetch docs."
        )

        if manim_code:
            input_text += (
                f"\n\nAlso validate this Manim code using the local tools "
                f"(validate_manim_imports, check_spatial_bounds, extract_scene_metadata):\n"
                f"```python\n{manim_code}\n```"
            )

        result = await runner.run(
            input=input_text,
            model="anthropic/claude-3-5-haiku-latest",
            mcp_servers=["tsion/context7"],  # MCP server
            tools=LOCAL_TOOLS,                # Local tools alongside MCP!
            instructions=(
                "You are a Manim documentation and validation assistant. "
                "Use Context7 MCP tools to fetch docs, and use the local tools "
                "to validate any provided code. Return the documentation text "
                "and any validation results."
            ),
            max_tokens=max_tokens,
            max_steps=8,
        )

        result_text = result.final_output or ""

        if result_text and len(result_text) > 100:
            logger.info(
                "  Fetched %d chars via Dedalus SDK (MCP + local tools)",
                len(result_text),
            )
            if result.tools_called:
                logger.info("  Tools called: %s", result.tools_called)

            if not manim_code:
                _docs_cache[cache_key] = result_text
            return result_text

        return ""
    except ImportError:
        logger.error("  dedalus-labs package not installed")
        return ""
    except Exception as exc:
        logger.error("  Dedalus SDK with tools failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Direct Context7 REST API fallback (no Dedalus SDK)
# ---------------------------------------------------------------------------

async def _resolve_library_id(library_name: str) -> Optional[str]:
    """
    Resolve a library name to a Context7 library ID.

    Context7 MCP tool: resolve-library-id
    Uses the /api/v2/search endpoint.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{CONTEXT7_API_BASE}/search",
                params={"query": library_name},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            if isinstance(data, dict):
                results = data.get("results", [])
            elif isinstance(data, list):
                results = data

            if results:
                for r in results:
                    rid = r.get("id", "")
                    if "community" in rid.lower() or "stable" in rid.lower():
                        logger.info(
                            "Context7: Resolved '%s' -> %s (%s, %d tokens)",
                            library_name, rid,
                            r.get("title"), r.get("totalTokens", 0),
                        )
                        return rid
                rid = results[0].get("id", "")
                logger.info("Context7: Resolved '%s' -> %s", library_name, rid)
                return rid

            logger.warning("Context7: No library found for '%s'", library_name)
            return None
    except Exception as exc:
        logger.error("Context7 resolve-library-id failed: %s", exc)
        return None


async def _get_library_docs(
    library_id: str,
    query: str = "animations mobjects scenes",
    max_tokens: int = 5000,
) -> Optional[str]:
    """
    Fetch documentation for a library from Context7.

    Context7 MCP tool: get-library-docs
    Uses the /api/v2/context endpoint.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{CONTEXT7_API_BASE}/context",
                params={
                    "libraryId": library_id,
                    "query": query,
                    "tokens": str(max_tokens),
                },
            )
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/plain" in content_type:
                return resp.text

            try:
                data = resp.json()
                if isinstance(data, dict):
                    return (
                        data.get("context")
                        or data.get("content")
                        or json.dumps(data, indent=2)
                    )
                return str(data)
            except Exception:
                return resp.text
    except Exception as exc:
        logger.error("Context7 get-library-docs failed: %s", exc)
        return None


async def fetch_manim_docs_direct(
    query: str = "animations mobjects Scene ThreeDScene",
    max_tokens: int = 5000,
) -> str:
    """
    Direct Context7 API fallback (no Dedalus SDK).

    Used when Dedalus is unavailable or for testing Context7 independently.
    """
    cache_key = f"direct:manim:{query}:{max_tokens}"
    if cache_key in _docs_cache:
        return _docs_cache[cache_key]

    logger.info("Context7 direct: Fetching docs for query '%s'", query)

    lib_id = await _resolve_library_id(MANIM_LIBRARY_NAME)
    if not lib_id:
        logger.warning("Context7: Could not resolve 'manim' library")
        return ""

    docs = await _get_library_docs(lib_id, query, max_tokens)
    if docs:
        logger.info("Context7 direct: Fetched %d chars", len(docs))
        _docs_cache[cache_key] = docs
        return docs

    return ""


# ---------------------------------------------------------------------------
# Main entry point with fallback chain
# ---------------------------------------------------------------------------

async def get_manim_docs(
    topic: str = "animations mobjects Scene ThreeDScene MathTex",
    max_tokens: int = 5000,
    use_dedalus: bool = True,
) -> str:
    """
    Main entry point: Fetch live Manim documentation.

    Fallback chain:
      1. Dedalus SDK + Context7 MCP (official SDK with native MCP support)
      2. Direct Context7 REST API
      3. Static manim_reference.md file

    Args:
        topic: What Manim APIs/concepts to look up
        max_tokens: Max documentation tokens
        use_dedalus: Whether to try Dedalus SDK first

    Returns:
        Documentation string (live or static fallback)
    """
    docs = ""

    if use_dedalus and DEDALUS_API_KEY:
        docs = await fetch_manim_docs_via_dedalus(topic, max_tokens)

    if not docs:
        docs = await fetch_manim_docs_direct(topic, max_tokens)

    if not docs:
        logger.info("All live doc sources failed, using static manim_reference.md")
        static_path = (
            Path(__file__).parent.parent / "prompts" / "system" / "manim_reference.md"
        )
        if static_path.exists():
            docs = static_path.read_text()

    return docs


def clear_docs_cache():
    """Clear the documentation cache (useful between pipeline runs)."""
    _docs_cache.clear()


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async def _test():
        print("=" * 60)
        print("Testing Dedalus SDK + Context7 MCP Integration")
        print("=" * 60)

        # Test 1: Dedalus SDK + Context7 MCP
        print("\n--- Test 1: Dedalus SDK + Context7 MCP ---")
        docs = await fetch_manim_docs_via_dedalus("animations Scene Create FadeIn MathTex")
        if docs:
            print(f"Got {len(docs)} chars of documentation via Dedalus SDK")
            print(f"  Preview: {docs[:200]}...")
        else:
            print("Dedalus SDK returned nothing")

        clear_docs_cache()

        # Test 2: Dedalus SDK with local tools + MCP
        print("\n--- Test 2: Dedalus SDK + MCP + Local Tools ---")
        sample_code = '''
from manim import *

class TestScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait(1)
'''
        result = await fetch_manim_docs_via_dedalus_with_tools(
            "Scene animations Create",
            max_tokens=3000,
            manim_code=sample_code,
        )
        if result:
            print(f"Got {len(result)} chars (docs + validation)")
            print(f"  Preview: {result[:200]}...")
        else:
            print("Dedalus SDK with tools returned nothing")

        clear_docs_cache()

        # Test 3: Direct Context7 fallback
        print("\n--- Test 3: Direct Context7 API (fallback) ---")
        docs = await fetch_manim_docs_direct("animations Scene Create FadeIn")
        if docs:
            print(f"Got {len(docs)} chars via direct Context7")
            print(f"  Preview: {docs[:200]}...")
        else:
            print("Direct API returned nothing")

        clear_docs_cache()

        # Test 4: Full pipeline entry point
        print("\n--- Test 4: Full get_manim_docs() ---")
        docs = await get_manim_docs("ThreeDScene 3D animations camera")
        if docs:
            print(f"Got {len(docs)} chars via full pipeline")
            print(f"  Preview: {docs[:200]}...")
        else:
            print("All methods failed")

        # Test 5: Local tools standalone
        print("\n--- Test 5: Local Tools (standalone) ---")
        test_code = "from manim import *\nclass Bad(Scene):\n  def construct(self):\n    pass"
        print(f"  validate_manim_imports: {validate_manim_imports(test_code)}")
        print(f"  check_spatial_bounds: {check_spatial_bounds(test_code)}")
        print(f"  extract_scene_metadata: {extract_scene_metadata(test_code)}")

    asyncio.run(_test())
