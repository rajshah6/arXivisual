"""Voiceover few-shot example for equation visualizations."""

from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.openai import OpenAIService


class VoiceoverEquationExample(VoiceoverScene):
    def construct(self):
        self.set_speech_service(OpenAIService(voice="nova", model="gpt-4o-mini-tts", transcription_model=None, cache_dir="/tmp/arxivisual-tts-cache"))

        # Beat 1: framing equation
        title = Text("Scaled Dot-Product Attention", font_size=38)
        with self.voiceover(text="We will unpack how attention converts similarity scores into context-sensitive outputs.") as tracker:
            self.play(Write(title), run_time=tracker.duration)
        self.play(title.animate.to_edge(UP, buff=0.6))

        # Beat 2: complete formula
        formula = MathTex(r"\text{Attention}(Q,K,V)=\text{softmax}(\frac{QK^T}{\sqrt{d_k}})V")
        formula.next_to(title, DOWN, buff=0.8)
        formula.set_color_by_tex("Q", BLUE)
        formula.set_color_by_tex("K", ORANGE)
        formula.set_color_by_tex("V", GREEN)

        with self.voiceover(text="Query-key dot products estimate relevance, then scaling stabilizes gradients during training.") as tracker:
            self.play(Write(formula), run_time=tracker.duration)

        # Beat 3: meaning of softmax weighting
        softmax_note = Text("Softmax -> normalized attention weights", font_size=26)
        softmax_note.next_to(formula, DOWN, buff=0.6)

        with self.voiceover(text="Softmax turns raw scores into probabilities, so each value contribution is proportionally weighted.") as tracker:
            self.play(FadeIn(softmax_note), run_time=tracker.duration)

        self.wait(0.5)
