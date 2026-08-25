"""Voiceover few-shot example for data-flow visualizations."""

from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.openai import OpenAIService


class VoiceoverDataFlowExample(VoiceoverScene):
    def construct(self):
        self.set_speech_service(OpenAIService(voice="nova", model="gpt-4o-mini-tts", transcription_model=None, cache_dir="/tmp/arxivisual-tts-cache"))

        # Beat 1: framing
        title = Text("Attention Data Flow", font_size=42)
        with self.voiceover(text="We will track how attention transforms token representations into contextual outputs.") as tracker:
            self.play(Write(title), run_time=tracker.duration)
        self.play(title.animate.to_edge(UP, buff=0.6))

        # Beat 2: query and key interactions
        query = RoundedRectangle(width=2.0, height=0.9, color=BLUE, fill_opacity=0.2)
        key = RoundedRectangle(width=2.0, height=0.9, color=ORANGE, fill_opacity=0.2)
        query_label = Text("Query", font_size=24).move_to(query)
        key_label = Text("Key", font_size=24).move_to(key)
        blocks = VGroup(VGroup(query, query_label), VGroup(key, key_label)).arrange(RIGHT, buff=1.0)
        blocks.next_to(title, DOWN, buff=0.9)

        with self.voiceover(text="Queries compare against keys to estimate which tokens are most relevant.") as tracker:
            self.play(FadeIn(blocks), run_time=tracker.duration)

        # Beat 3: weighted output
        value = RoundedRectangle(width=2.0, height=0.9, color=GREEN, fill_opacity=0.2)
        value_label = Text("Value", font_size=24).move_to(value)
        value_group = VGroup(value, value_label).next_to(blocks, DOWN, buff=0.8)
        arrow_q = Arrow(query.get_bottom(), value.get_top(), buff=0.1)
        arrow_k = Arrow(key.get_bottom(), value.get_top(), buff=0.1)

        with self.voiceover(text="Softmax-normalized scores weight values, producing context-aware representations for each token.") as tracker:
            self.play(FadeIn(value_group), Create(arrow_q), Create(arrow_k), run_time=tracker.duration)

        self.wait(0.6)
