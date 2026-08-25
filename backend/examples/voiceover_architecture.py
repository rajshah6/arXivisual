"""Voiceover few-shot example for architecture visualizations."""

from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.openai import OpenAIService


class VoiceoverArchitectureExample(VoiceoverScene):
    def construct(self):
        self.set_speech_service(OpenAIService(voice="nova", model="gpt-4o-mini-tts", transcription_model=None))

        # Beat 1: frame architecture objective
        title = Text("Transformer Encoder Block", font_size=40)
        with self.voiceover(text="This encoder block combines attention and feed-forward layers with residual pathways.") as tracker:
            self.play(Write(title), run_time=tracker.duration)
        self.play(title.animate.to_edge(UP, buff=0.6))

        # Beat 2: core modules
        attn = Rectangle(width=3.2, height=0.9, color=BLUE, fill_opacity=0.2)
        ffn = Rectangle(width=3.2, height=0.9, color=GREEN, fill_opacity=0.2)
        norm = Rectangle(width=3.2, height=0.9, color=ORANGE, fill_opacity=0.2)
        layers = VGroup(attn, norm, ffn).arrange(DOWN, buff=0.45).next_to(title, DOWN, buff=0.8)

        labels = VGroup(
            Text("Self-Attention", font_size=24).move_to(attn),
            Text("LayerNorm", font_size=24).move_to(norm),
            Text("Feed-Forward", font_size=24).move_to(ffn),
        )

        with self.voiceover(text="Attention mixes contextual information, while normalization and feed-forward layers refine representations.") as tracker:
            self.play(FadeIn(layers), FadeIn(labels), run_time=tracker.duration)

        # Beat 3: residual flow
        bypass = CurvedArrow(attn.get_left() + LEFT * 0.3, ffn.get_left() + LEFT * 0.3, angle=-PI / 2)
        with self.voiceover(text="Residual connections preserve earlier signals, making deep optimization more stable and expressive.") as tracker:
            self.play(Create(bypass), run_time=tracker.duration)

        self.wait(0.5)
