"""
Voiceover Generator Agent for adding narration to Manim visualizations.

Uses manim-voiceover library to add AI-generated speech that syncs with animations.
See: https://docs.manim.community/en/stable/guides/add_voiceovers.html

Features:
1. Generates voiceover script from visualization plan
2. Transforms Scene to VoiceoverScene
3. Wraps animations with voiceover blocks
4. Supports multiple TTS backends (gTTS, Azure, ElevenLabs)
"""

import re
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

# Handle imports for both package and direct execution
try:
    from .base import BaseAgent
    from ..models.generation import VisualizationPlan, Scene
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.base import BaseAgent
    from models.generation import VisualizationPlan, Scene


class VoiceoverScript(BaseModel):
    """Generated voiceover script for a visualization."""
    
    scene_narrations: list[str] = Field(
        default_factory=list,
        description="Narration text for each scene"
    )
    intro: str = Field("", description="Introduction narration")
    outro: str = Field("", description="Closing narration")


class VoiceoverOutput(BaseModel):
    """Output from the Voiceover Generator."""
    
    transformed_code: str = Field(..., description="Manim code with voiceover integration")
    script: VoiceoverScript = Field(..., description="The generated voiceover script")
    tts_service: str = Field("gtts", description="TTS service used (gtts, azure, elevenlabs)")


class VoiceoverGenerator(BaseAgent):
    """
    Generates voiceover scripts and transforms Manim code to include narration.
    
    The agent:
    1. Creates concise narration for each scene in the visualization
    2. Transforms Scene classes to VoiceoverScene
    3. Wraps self.play() calls with voiceover blocks
    """
    
    # TTS service import statements
    TTS_IMPORTS = {
        "gtts": "from manim_voiceover.services.gtts import GTTSService",
        "azure": "from manim_voiceover.services.azure import AzureService",
        "elevenlabs": "from manim_voiceover.services.elevenlabs import ElevenLabsService",
        "recorder": "from manim_voiceover.services.recorder import RecorderService",
    }
    
    # TTS service setup code
    # Note: ElevenLabs requires ELEVEN_API_KEY environment variable
    # Using voice_id for ElevenLabs to avoid needing "voices_read" API permission
    # model="eleven_flash_v2_5" - fastest and cheapest option
    # transcription_model=None avoids whisper dependency issues on Python 3.13
    TTS_SETUP = {
        "gtts": "self.set_speech_service(GTTSService())",
        "azure": 'self.set_speech_service(AzureService(voice="en-US-AriaNeural"))',
        "elevenlabs": 'self.set_speech_service(ElevenLabsService(voice_id="2fe8mwpfJcqvj9RGBsC1", model="eleven_flash_v2_5", transcription_model=None))',  # Custom voice
        "recorder": "self.set_speech_service(RecorderService())",
    }
    
    # Available ElevenLabs voices with their IDs (use voice_id to bypass API permission issues)
    # Using voice_id instead of voice_name avoids needing "voices_read" API permission
    ELEVENLABS_VOICES = {
        "Custom": "2fe8mwpfJcqvj9RGBsC1",     # User's preferred voice
        "Adam": "pNInz6obpgDQGcFmaJgB",       # Deep, warm male voice
        "Antoni": "ErXwobaYiN019PkySvjV",     # Young male voice  
        "Arnold": "VR6AewLTigWG4xSOukaG",     # Authoritative male voice
        "Bella": "EXAVITQu4vr4xnSDxMaL",      # Friendly female voice
        "Domi": "AZnzlk1XvdvUeBnXmlld",       # Strong female voice
        "Elli": "MF3mGyEYCl7XYWbV9V6O",       # Young female voice
        "Josh": "TxGEqnHWrfWFTfGW9XjX",       # Conversational male voice
        "Rachel": "21m00Tcm4TlvDq8ikWAM",     # Clear female voice
        "Sam": "yoZ06aMxZJJ28mfd3POQ",        # Neutral voice
    }
    
    def __init__(
        self,
        model: str | None = None,
        tts_service: str = "elevenlabs",
        voice_name: str = "Custom",
    ):
        """
        Initialize the Voiceover Generator.

        Args:
            model: LLM model to use for script generation
            tts_service: TTS service to use (gtts, azure, elevenlabs, recorder)
            voice_name: Voice name for ElevenLabs (default: "Adam")
                       See ELEVENLABS_VOICES for available options.

        Note:
            For ElevenLabs, set ELEVEN_API_KEY environment variable.
            For Azure, set AZURE_SUBSCRIPTION_KEY and AZURE_SERVICE_REGION.

            ElevenLabs uses voice_id internally to avoid needing "voices_read" permission.
        """
        super().__init__(prompt_file="voiceover_generator.md", model=model)
        self.tts_service = tts_service
        self.voice_name = voice_name
        
        # Update ElevenLabs setup with the appropriate voice_id
        if tts_service == "elevenlabs":
            voice_id = self.ELEVENLABS_VOICES.get(voice_name, self.ELEVENLABS_VOICES["Adam"])
            self.TTS_SETUP = self.TTS_SETUP.copy()
            self.TTS_SETUP["elevenlabs"] = f'self.set_speech_service(ElevenLabsService(voice_id="{voice_id}", model="eleven_flash_v2_5", transcription_model=None))'
    
    async def run(
        self,
        plan: VisualizationPlan,
        manim_code: str,
    ) -> VoiceoverOutput:
        """
        Generate voiceover and transform Manim code.
        
        Args:
            plan: The visualization plan with scene descriptions
            manim_code: The original Manim code
            
        Returns:
            VoiceoverOutput with transformed code and script
        """
        # Generate educational voiceover script using LLM
        script = await self._generate_script(plan)
        
        # Transform the code to include voiceovers
        transformed_code = self._transform_code(manim_code, script)
        
        return VoiceoverOutput(
            transformed_code=transformed_code,
            script=script,
            tts_service=self.tts_service,
        )
    
    async def _generate_script(self, plan: VisualizationPlan) -> VoiceoverScript:
        """
        Generate educational voiceover script using LLM.
        
        Uses the narration_points from the plan as guidance and generates
        human-like educational narration that explains the concept.
        """
        # Use narration_points if available, otherwise generate from concept
        if plan.narration_points and len(plan.narration_points) > 0:
            # Use the pre-planned educational narration points
            narrations = self._expand_narration_points(plan)
        else:
            # Generate narration using LLM
            narrations = await self._generate_narrations_with_llm(plan)
        
        # Create intro and outro
        intro = f"Let's explore {plan.concept_name}."
        outro = ""  # No outro needed - ends naturally
        
        return VoiceoverScript(
            scene_narrations=narrations,
            intro=intro,
            outro=outro,
        )
    
    def _expand_narration_points(self, plan: VisualizationPlan) -> list[str]:
        """
        Return narration points for content scenes.
        
        narration_points are educational explanations from the planner.
        These will be placed at scene boundaries (Scene 2, Scene 3, etc.)
        Scene 1 is skipped (title scene - no narration needed).
        
        Returns a list where index 0 = narration for Scene 2, index 1 = Scene 3, etc.
        """
        narration_points = plan.narration_points or []
        
        # Filter out any bad narrations (animation commands that slipped through)
        bad_starts = ["display", "show", "fade", "animate", "create", "draw", "move", "write"]
        filtered = []
        for narration in narration_points:
            if narration and narration.strip():
                lower = narration.lower().strip()
                if not any(lower.startswith(bad) for bad in bad_starts):
                    filtered.append(narration)
        
        return filtered
    
    async def _generate_narrations_with_llm(self, plan: VisualizationPlan) -> list[str]:
        """Generate educational narrations using the LLM."""
        prompt = f"""Generate educational voiceover narration for a visualization about "{plan.concept_name}".

The visualization has {len(plan.scenes)} scenes. Generate ONE short educational sentence per scene.

IMPORTANT RULES:
- Be educational - explain the CONCEPT, not the animation
- Be concise - each narration should be 10-20 words MAX
- Sound natural - like a teacher explaining to a student
- NO animation commands - don't say "display", "fade in", "show", "animate"
- NO technical jargon about visuals - don't describe what appears on screen
- Focus on the ML/AI concept being taught

Example GOOD narrations:
- "The attention mechanism allows the model to focus on relevant parts of the input."
- "Each query vector searches for matching keys to determine importance."
- "The softmax function converts raw scores into probabilities that sum to one."

Example BAD narrations (DO NOT generate these):
- "Display the title at the center of the screen"
- "Fade in the components one by one"
- "Show arrows connecting the boxes"

Generate {len(plan.scenes)} educational sentences, one per line:"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parse response - one narration per line
        text = response.content[0].text
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        
        # Filter out any lines that look like animation commands
        filtered = []
        bad_starts = ["display", "show", "fade", "animate", "create", "draw", "move", "write"]
        for line in lines:
            # Remove numbering like "1.", "1)", etc.
            clean = line.lstrip("0123456789.-) ").strip()
            # Check if it starts with animation command
            lower = clean.lower()
            if not any(lower.startswith(bad) for bad in bad_starts):
                filtered.append(clean)
            else:
                filtered.append("")  # Skip bad narrations
        
        # Pad or trim to match scene count
        while len(filtered) < len(plan.scenes):
            filtered.append("")
        return filtered[:len(plan.scenes)]
    
    def _transform_code(self, code: str, script: VoiceoverScript) -> str:
        """
        Transform Manim code to include voiceover integration.
        
        Transformations:
        1. Add manim_voiceover imports
        2. Change Scene to VoiceoverScene
        3. Add TTS service setup
        4. Place voiceovers at scene boundaries (# Scene N: comments)
        
        Key improvement: Narrations are placed at SCENE BOUNDARIES, not on
        every self.play() call. This ensures narration matches the visual content.
        """
        lines = code.split("\n")
        new_lines = []
        
        # Track state
        in_class = False
        in_construct = False
        class_indent = ""
        construct_indent = ""
        added_tts_setup = False
        
        # Track scene boundaries for narration placement
        current_scene = 0  # 0 = before any scene
        pending_narration = None  # Narration to add at next self.play()
        narration_used = set()  # Track which scenes got narration
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Add voiceover imports after manim import
            if stripped.startswith("from manim import"):
                new_lines.append(line)
                new_lines.append("from manim_voiceover import VoiceoverScene")
                new_lines.append(self.TTS_IMPORTS.get(self.tts_service, self.TTS_IMPORTS["gtts"]))
                continue
            
            # Transform Scene to VoiceoverScene
            if re.match(r"class\s+\w+\s*\(\s*Scene\s*\)", stripped):
                line = line.replace("(Scene)", "(VoiceoverScene)")
                in_class = True
                class_indent = self._get_indent(line)
                new_lines.append(line)
                continue
            
            # Detect construct method
            if in_class and "def construct(self)" in stripped:
                in_construct = True
                construct_indent = self._get_indent(line)
                new_lines.append(line)
                
                # Add TTS setup as first line in construct
                if not added_tts_setup:
                    setup_indent = construct_indent + "    "
                    new_lines.append(f"{setup_indent}{self.TTS_SETUP.get(self.tts_service, self.TTS_SETUP['gtts'])}")
                    added_tts_setup = True
                continue
            
            # Detect scene boundary comments like "# Scene 1:", "# Scene 2:", etc.
            scene_match = re.match(r"#\s*Scene\s*(\d+)", stripped, re.IGNORECASE)
            if in_construct and scene_match:
                scene_num = int(scene_match.group(1))
                current_scene = scene_num
                
                # Get narration for this scene (skip scene 1 which is usually title)
                # Map: Scene 2 -> narration[0], Scene 3 -> narration[1], etc.
                narration_idx = scene_num - 2  # Scene 2 gets first narration
                if narration_idx >= 0 and narration_idx < len(script.scene_narrations):
                    narration = script.scene_narrations[narration_idx]
                    if narration and narration.strip() and narration_idx not in narration_used:
                        pending_narration = narration
                        narration_used.add(narration_idx)
                
                new_lines.append(line)
                continue
            
            # Place pending narration at the first self.play() after scene comment
            if in_construct and stripped.startswith("self.play(") and pending_narration:
                narration = pending_narration.replace('"', '\\"')
                current_indent = self._get_indent(line)
                
                # Add voiceover block
                new_lines.append(f'{current_indent}with self.voiceover(text="{narration}") as tracker:')
                timed_play = self._ensure_tracker_runtime(stripped)
                new_lines.append(f"{current_indent}    {timed_play}")
                pending_narration = None  # Clear pending
                continue
            
            # Keep track of when we exit class/method
            if in_class and stripped and not stripped.startswith("#"):
                current_indent_len = len(line) - len(line.lstrip())
                if current_indent_len <= len(class_indent) and stripped.startswith("class "):
                    in_class = False
                    in_construct = False
            
            new_lines.append(line)
        
        return "\n".join(new_lines)
    
    def _get_indent(self, line: str) -> str:
        """Get the indentation of a line."""
        return line[:len(line) - len(line.lstrip())]

    def _ensure_tracker_runtime(self, play_call_line: str) -> str:
        """Ensure narrated self.play call uses tracker duration for sync."""
        if "run_time=tracker.duration" in play_call_line:
            return play_call_line
        if not play_call_line.endswith(")"):
            return play_call_line
        return play_call_line[:-1] + ", run_time=tracker.duration)"
    
    def generate_script_only(self, plan: VisualizationPlan) -> VoiceoverScript:
        """
        Generate just the voiceover script without transforming code.
        
        Useful for reviewing/editing scripts before applying.
        """
        import asyncio
        return asyncio.run(self._generate_script(plan))


# Create a simple prompt file for the voiceover generator
VOICEOVER_PROMPT = """You are an expert at creating concise, educational voiceover narration
for mathematical and technical visualizations.

Given a visualization plan, generate clear and engaging narration that:
1. Explains what the viewer is seeing
2. Uses simple, accessible language
3. Keeps each narration under 15 seconds (about 40 words)
4. Focuses on the key concept being illustrated

Plan:
{plan_json}

Generate narration for each scene:
"""


def create_voiceover_prompt_file():
    """Create the voiceover generator prompt file if it doesn't exist."""
    prompt_dir = Path(__file__).parent.parent / "prompts"
    prompt_file = prompt_dir / "voiceover_generator.md"
    
    if not prompt_file.exists():
        prompt_file.write_text(VOICEOVER_PROMPT)
        print(f"Created {prompt_file}")


# For testing
if __name__ == "__main__":
    # Sample Manim code
    sample_code = '''from manim import *

class AttentionVisualization(Scene):
    def construct(self):
        title = Text("Attention Mechanism")
        self.play(Write(title))
        self.wait(1)
        
        self.play(title.animate.to_edge(UP))
        
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        self.wait(0.5)
        
        self.play(FadeOut(circle))
        self.wait(1)
'''
    
    # Sample script
    sample_script = VoiceoverScript(
        intro="Let's explore the attention mechanism.",
        scene_narrations=[
            "First, we introduce the attention mechanism concept.",
            "The title moves to make room for our visualization.",
            "Here we show a circle representing a key component.",
            "Finally, we fade out to conclude this section.",
        ],
        outro="This was a simple demonstration of attention."
    )
    
    # Create a minimal generator for testing (without LLM initialization)
    class TestVoiceoverGenerator:
        """Minimal generator for testing transformation without LLM."""
        tts_service = "elevenlabs"
        TTS_IMPORTS = VoiceoverGenerator.TTS_IMPORTS
        TTS_SETUP = VoiceoverGenerator.TTS_SETUP
        
        def _get_indent(self, line: str) -> str:
            return line[:len(line) - len(line.lstrip())]
        
        _transform_code = VoiceoverGenerator._transform_code
    
    generator = TestVoiceoverGenerator()
    transformed = generator._transform_code(sample_code, sample_script)
    
    print("Original code:")
    print("-" * 40)
    print(sample_code)
    print("\nTransformed code with voiceover (ElevenLabs):")
    print("-" * 40)
    print(transformed)
