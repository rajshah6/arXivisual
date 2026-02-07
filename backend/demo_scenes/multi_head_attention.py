"""
Scene 2: Multi-Head Attention — viz_002
Maps to section-3-3 of "Attention Is All You Need"

Inspired by 3Blue1Brown's transformer visualizations.
Shows how multiple attention heads work in parallel and combine.

Works without LaTeX (uses Text instead of MathTex).
"""
from manim import *
import numpy as np


# 3b1b-inspired palette
Q_COLOR = YELLOW
K_COLOR = TEAL
V_COLOR = RED
ACCENT = ManimColor("#3B82F6")
GOLD = ManimColor("#F59E0B")
SOFT_WHITE = ManimColor("#E2E8F0")
DIM_COLOR = ManimColor("#64748B")

# Colors for different heads
HEAD_COLORS = [
    ManimColor("#FF6B6B"),  # Coral red
    ManimColor("#4ECDC4"),  # Teal
    ManimColor("#45B7D1"),  # Sky blue
    ManimColor("#96CEB4"),  # Sage green
    ManimColor("#FFEAA7"),  # Soft yellow
    ManimColor("#DDA0DD"),  # Plum
    ManimColor("#FF8C42"),  # Orange
    ManimColor("#98D8C8"),  # Mint
]


class MultiHeadAttention(Scene):
    def construct(self):
        # ── Beat 1: Title ──────────────────────────────────────
        title = Text("Multi-Head Attention", font_size=42, color=WHITE)
        subtitle = Text(
            "Attending to different representation subspaces",
            font_size=18, color=DIM_COLOR,
        )
        title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.3)
        title_group.move_to(ORIGIN)

        self.play(Write(title, run_time=1.2))
        self.play(FadeIn(subtitle, shift=UP * 0.2))
        self.wait(0.8)
        self.play(
            title.animate.scale(0.55).to_edge(UP, buff=0.2),
            FadeOut(subtitle),
            run_time=0.7,
        )

        # ── Beat 2: The problem — single head limitation ──────
        problem_text = Text(
            "A single attention head can only focus on one pattern...",
            font_size=18, color=SOFT_WHITE,
        )
        problem_text.next_to(title, DOWN, buff=0.4)
        self.play(Write(problem_text, run_time=0.8))

        # Show a single attention head as a small block
        def make_attention_head(head_num, color, scale=1.0):
            """Create a visual representation of one attention head."""
            box = RoundedRectangle(
                width=2.0 * scale, height=1.4 * scale,
                corner_radius=0.1,
                fill_color=color, fill_opacity=0.15,
                stroke_color=color, stroke_width=2,
            )

            head_label = Text(f"Head {head_num}", font_size=int(16 * scale), color=color, weight=BOLD)
            head_label.move_to(box.get_top() + DOWN * 0.25 * scale)

            # Mini Q K V inside
            q = Text("Q", font_size=int(12 * scale), color=Q_COLOR)
            k = Text("K", font_size=int(12 * scale), color=K_COLOR)
            v = Text("V", font_size=int(12 * scale), color=V_COLOR)
            qkv = VGroup(q, k, v).arrange(RIGHT, buff=0.15 * scale)
            qkv.next_to(head_label, DOWN, buff=0.15 * scale)

            # Mini attention grid (3x3)
            mini_grid = VGroup()
            for i in range(3):
                for j in range(3):
                    intensity = np.random.random() * 0.7 + 0.1
                    if i == j:
                        intensity = min(intensity + 0.4, 1.0)
                    cell = Square(
                        side_length=0.15 * scale,
                        fill_color=interpolate_color(BLACK, color, intensity),
                        fill_opacity=0.8,
                        stroke_width=0,
                    )
                    cell.shift(RIGHT * j * 0.16 * scale + DOWN * i * 0.16 * scale)
                    mini_grid.add(cell)
            mini_grid.next_to(qkv, DOWN, buff=0.1 * scale)

            return VGroup(box, head_label, qkv, mini_grid)

        single_head = make_attention_head(1, HEAD_COLORS[0], scale=1.2)
        single_head.move_to(ORIGIN + DOWN * 0.3)

        self.play(FadeIn(single_head, scale=0.9), run_time=0.8)
        self.wait(0.5)

        # Show single head can capture "who does what"
        caption1 = Text(
            '"cat" attends to "sat" (subject-verb)',
            font_size=14, color=HEAD_COLORS[0],
        )
        caption1.next_to(single_head, DOWN, buff=0.3)
        self.play(FadeIn(caption1))
        self.wait(0.5)

        # ── Beat 3: The solution — multiple heads ─────────────
        solution_text = Text(
            "Solution: Use multiple heads to capture different patterns!",
            font_size=18, color=GOLD,
        )
        solution_text.move_to(problem_text)

        self.play(
            Transform(problem_text, solution_text),
            FadeOut(caption1),
            run_time=0.6,
        )

        # Shrink single head and replicate into 8 heads
        self.play(
            single_head.animate.scale(0.4).move_to(LEFT * 5.5 + DOWN * 0.8),
            run_time=0.6,
        )

        # Create 8 heads in two rows
        num_heads = 8
        heads = VGroup()
        for i in range(num_heads):
            h = make_attention_head(i + 1, HEAD_COLORS[i], scale=0.7)
            heads.add(h)

        # Arrange in 2 rows of 4
        row1 = VGroup(*heads[:4]).arrange(RIGHT, buff=0.3)
        row2 = VGroup(*heads[4:]).arrange(RIGHT, buff=0.3)
        heads_layout = VGroup(row1, row2).arrange(DOWN, buff=0.3)
        heads_layout.move_to(ORIGIN + DOWN * 0.5)

        # Remove the single head and show all 8
        self.play(
            FadeOut(single_head),
            LaggedStart(
                *[FadeIn(h, scale=0.8) for h in heads],
                lag_ratio=0.06,
            ),
            run_time=1.5,
        )
        self.wait(0.5)

        # ── Beat 4: Show what each head learns ────────────────
        head_descriptions = [
            "subject-verb",
            "adjective-noun",
            "positional (nearby)",
            "coreference",
            "syntactic deps",
            "semantic roles",
            "long-range",
            "rare patterns",
        ]

        desc_labels = VGroup()
        for i, desc in enumerate(head_descriptions):
            dl = Text(desc, font_size=9, color=HEAD_COLORS[i])
            dl.next_to(heads[i], DOWN, buff=0.08)
            desc_labels.add(dl)

        self.play(
            LaggedStart(
                *[FadeIn(dl, shift=UP * 0.1) for dl in desc_labels],
                lag_ratio=0.05,
            ),
            run_time=1.0,
        )
        self.wait(1.0)

        # ── Beat 5: Concatenation step ────────────────────────
        self.play(
            FadeOut(desc_labels),
            FadeOut(problem_text),
            run_time=0.5,
        )

        concat_label = Text("Step 1: Concatenate all heads", font_size=20, color=GOLD)
        concat_label.next_to(title, DOWN, buff=0.35)
        self.play(Write(concat_label, run_time=0.6))

        # Animate heads shrinking and moving together
        concat_target = VGroup()
        for i, h in enumerate(heads):
            thin_block = RoundedRectangle(
                width=0.35, height=1.8,
                corner_radius=0.05,
                fill_color=HEAD_COLORS[i], fill_opacity=0.3,
                stroke_color=HEAD_COLORS[i], stroke_width=1.5,
            )
            concat_target.add(thin_block)

        concat_target.arrange(RIGHT, buff=0.04)
        concat_target.move_to(LEFT * 2 + DOWN * 0.5)

        # Bracket around concatenated
        concat_bracket_l = Text("[", font_size=60, color=WHITE)
        concat_bracket_l.next_to(concat_target, LEFT, buff=0.05)
        concat_bracket_r = Text("]", font_size=60, color=WHITE)
        concat_bracket_r.next_to(concat_target, RIGHT, buff=0.05)

        concat_text = Text("Concat", font_size=14, color=DIM_COLOR)
        concat_text.next_to(concat_target, UP, buff=0.15)

        self.play(
            *[Transform(heads[i], concat_target[i]) for i in range(num_heads)],
            run_time=1.2,
        )
        self.play(
            FadeIn(concat_bracket_l), FadeIn(concat_bracket_r),
            FadeIn(concat_text),
        )
        self.wait(0.5)

        # ── Beat 6: Linear projection W^O ─────────────────────
        proj_label = Text("Step 2: Linear projection W^O", font_size=20, color=GOLD)
        proj_label.move_to(concat_label)
        self.play(Transform(concat_label, proj_label), run_time=0.5)

        # W^O matrix
        wo_matrix = RoundedRectangle(
            width=1.2, height=1.8,
            corner_radius=0.1,
            fill_color=PURPLE, fill_opacity=0.2,
            stroke_color=PURPLE, stroke_width=2,
        )
        wo_label = Text("W^O", font_size=20, color=PURPLE, weight=BOLD)
        wo_label.move_to(wo_matrix)
        wo_group = VGroup(wo_matrix, wo_label)
        wo_group.next_to(concat_target, RIGHT, buff=0.8)

        # Arrow from concat to W^O
        mult_arrow = Arrow(
            concat_bracket_r.get_right(), wo_group.get_left(),
            color=WHITE, stroke_width=2, buff=0.15,
        )
        times_label = Text("x", font_size=18, color=WHITE)
        times_label.move_to(mult_arrow)

        self.play(
            GrowArrow(mult_arrow),
            FadeIn(times_label),
            FadeIn(wo_group, shift=LEFT * 0.3),
            run_time=0.8,
        )

        # Output
        output_rect = RoundedRectangle(
            width=1.2, height=1.8,
            corner_radius=0.1,
            fill_color=GREEN, fill_opacity=0.2,
            stroke_color=GREEN, stroke_width=2,
        )
        output_label = Text("Output", font_size=18, color=GREEN, weight=BOLD)
        output_label.move_to(output_rect)
        output_group = VGroup(output_rect, output_label)
        output_group.next_to(wo_group, RIGHT, buff=0.8)

        eq_arrow = Arrow(
            wo_group.get_right(), output_group.get_left(),
            color=WHITE, stroke_width=2, buff=0.15,
        )
        eq_label = Text("=", font_size=22, color=WHITE)
        eq_label.move_to(eq_arrow)

        self.play(
            GrowArrow(eq_arrow),
            FadeIn(eq_label),
            FadeIn(output_group, shift=LEFT * 0.3),
            run_time=0.8,
        )
        self.wait(0.5)

        # ── Beat 7: Dimension annotation ──────────────────────
        dim_text = Text(
            "8 heads x 64 dims = 512 dims  -->  W^O projects back to d_model",
            font_size=14, color=DIM_COLOR,
        )
        dim_text.next_to(concat_target, DOWN, buff=0.6)
        self.play(FadeIn(dim_text, shift=UP * 0.1))
        self.wait(0.5)

        # ── Beat 8: Final formula ─────────────────────────────
        final_eq = Text(
            "MultiHead(Q,K,V) = Concat(head_1,...,head_h) W^O",
            font_size=22, color=WHITE,
        )
        head_eq = Text(
            "where head_i = Attention(Q W_i^Q, K W_i^K, V W_i^V)",
            font_size=18, color=DIM_COLOR,
        )
        eq_group = VGroup(final_eq, head_eq).arrange(DOWN, buff=0.2)
        eq_group.to_edge(DOWN, buff=0.3)

        box = SurroundingRectangle(eq_group, color=GOLD, buff=0.2, corner_radius=0.1)

        self.play(
            FadeOut(dim_text),
            Write(final_eq, run_time=1.0),
        )
        self.play(FadeIn(head_eq, shift=UP * 0.1))
        self.play(Create(box))

        # Pulse
        self.play(
            box.animate.set_stroke(width=4),
            rate_func=there_and_back,
            run_time=0.8,
        )
        self.wait(2)
