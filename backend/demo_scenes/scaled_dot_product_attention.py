"""
Scene 1: Scaled Dot-Product Attention — viz_001
Maps to section-3-2 of "Attention Is All You Need"

Inspired by 3Blue1Brown's transformer visualizations.
Color convention: YELLOW=Q, TEAL=K, RED=V

Works without LaTeX (uses Text instead of MathTex).
"""
from manim import *
import numpy as np


# 3b1b-inspired palette
Q_COLOR = YELLOW
K_COLOR = TEAL
V_COLOR = RED
ACCENT = ManimColor("#3B82F6")  # 3b1b blue
GOLD = ManimColor("#F59E0B")  # 3b1b gold
SOFT_WHITE = ManimColor("#E2E8F0")
DIM_COLOR = ManimColor("#64748B")
BG_DARK = ManimColor("#1E293B")


class ScaledDotProductAttention(Scene):
    def construct(self):
        # ── Beat 1: Title ──────────────────────────────────────
        title = Text("Scaled Dot-Product Attention", font_size=40, color=WHITE)
        subtitle = Text(
            '"Attention Is All You Need" — Vaswani et al., 2017',
            font_size=18,
            color=DIM_COLOR,
        )
        title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.3)
        title_group.move_to(ORIGIN)

        self.play(Write(title, run_time=1.5))
        self.play(FadeIn(subtitle, shift=UP * 0.2))
        self.wait(1)
        self.play(
            title.animate.scale(0.6).to_edge(UP, buff=0.25),
            FadeOut(subtitle),
            run_time=0.8,
        )

        # ── Beat 2: Input tokens ──────────────────────────────
        words = ["The", "cat", "sat", "on", "the", "mat"]
        token_colors = [BLUE_C, BLUE_B, BLUE_A, BLUE_C, BLUE_B, BLUE_A]

        tokens = VGroup()
        for i, word in enumerate(words):
            box = RoundedRectangle(
                width=0.9, height=0.55, corner_radius=0.08,
                fill_color=token_colors[i], fill_opacity=0.25,
                stroke_color=token_colors[i], stroke_width=1.5,
            )
            label = Text(word, font_size=18, color=WHITE)
            label.move_to(box)
            tokens.add(VGroup(box, label))

        tokens.arrange(RIGHT, buff=0.15)
        tokens.next_to(title, DOWN, buff=0.55)

        input_label = Text("Input Tokens", font_size=16, color=DIM_COLOR)
        input_label.next_to(tokens, LEFT, buff=0.4)

        self.play(
            LaggedStart(
                *[FadeIn(t, shift=DOWN * 0.2) for t in tokens],
                lag_ratio=0.08,
            ),
            FadeIn(input_label),
            run_time=1.2,
        )
        self.wait(0.5)

        # ── Beat 3: Create Q, K, V from embeddings ────────────
        def make_matrix_block(label_text, color, width=1.4, height=1.6):
            rect = RoundedRectangle(
                width=width, height=height, corner_radius=0.1,
                fill_color=color, fill_opacity=0.15,
                stroke_color=color, stroke_width=2,
            )
            label = Text(label_text, font_size=28, color=color, weight=BOLD)
            label.move_to(rect.get_top() + DOWN * 0.3)

            # Grid lines inside to suggest matrix structure
            grid = VGroup()
            for j in range(4):
                y = rect.get_top()[1] - 0.55 - j * 0.22
                line = Line(
                    start=rect.get_left() + RIGHT * 0.15 + UP * (y - rect.get_center()[1]),
                    end=rect.get_right() + LEFT * 0.15 + UP * (y - rect.get_center()[1]),
                    stroke_width=0.5, color=color, stroke_opacity=0.3,
                )
                grid.add(line)

            return VGroup(rect, label, grid)

        q_block = make_matrix_block("Q", Q_COLOR)
        k_block = make_matrix_block("K", K_COLOR)
        v_block = make_matrix_block("V", V_COLOR)

        qkv_group = VGroup(q_block, k_block, v_block)
        qkv_group.arrange(RIGHT, buff=0.8)
        qkv_group.next_to(tokens, DOWN, buff=0.7)

        # W_Q, W_K, W_V labels (weight matrices)
        wq_label = Text("W_Q", font_size=14, color=Q_COLOR).next_to(q_block, UP, buff=0.15)
        wk_label = Text("W_K", font_size=14, color=K_COLOR).next_to(k_block, UP, buff=0.15)
        wv_label = Text("W_V", font_size=14, color=V_COLOR).next_to(v_block, UP, buff=0.15)

        # Arrows from tokens to Q, K, V
        arrows_to_qkv = VGroup()
        for block, color in [(q_block, Q_COLOR), (k_block, K_COLOR), (v_block, V_COLOR)]:
            arrow = Arrow(
                tokens.get_bottom(), block.get_top(),
                color=color, stroke_width=2, buff=0.1,
                max_tip_length_to_length_ratio=0.08,
            )
            arrows_to_qkv.add(arrow)

        self.play(
            LaggedStart(
                *[GrowArrow(a) for a in arrows_to_qkv],
                lag_ratio=0.15,
            ),
            run_time=0.8,
        )
        self.play(
            LaggedStart(
                FadeIn(q_block, shift=DOWN * 0.3),
                FadeIn(k_block, shift=DOWN * 0.3),
                FadeIn(v_block, shift=DOWN * 0.3),
                lag_ratio=0.12,
            ),
            FadeIn(wq_label), FadeIn(wk_label), FadeIn(wv_label),
            run_time=1.0,
        )
        self.wait(0.8)

        # ── Beat 4: Transition — clear and show attention computation ──
        old_elements = VGroup(tokens, input_label, arrows_to_qkv, wq_label, wk_label, wv_label)
        self.play(
            FadeOut(old_elements),
            qkv_group.animate.scale(0.7).to_edge(UP, buff=0.6).shift(LEFT * 3.5),
            FadeOut(title),
            run_time=0.8,
        )

        # ── Beat 5: QK^T dot product — attention score grid ───
        step_label = Text("Step 1: Compute Attention Scores", font_size=22, color=GOLD)
        step_label.to_edge(UP, buff=0.2)
        self.play(Write(step_label, run_time=0.6))

        # Formula
        formula_text = Text("scores = Q · K^T", font_size=20, color=WHITE)
        formula_text.next_to(step_label, DOWN, buff=0.3)
        self.play(FadeIn(formula_text))

        # Create attention score grid (6x6 for 6 tokens)
        n = 6
        grid_size = 0.45
        grid = VGroup()
        score_values = np.random.rand(n, n) * 2 - 0.5  # Random-ish scores

        # Make diagonal stronger (self-attention is often strong)
        for i in range(n):
            score_values[i][i] += 1.5

        for i in range(n):
            for j in range(n):
                val = score_values[i][j]
                intensity = np.clip((val + 0.5) / 3.0, 0.05, 1.0)
                cell = Square(
                    side_length=grid_size,
                    fill_color=interpolate_color(BLACK, GOLD, intensity),
                    fill_opacity=0.8,
                    stroke_color=WHITE,
                    stroke_width=0.5,
                    stroke_opacity=0.3,
                )
                cell.move_to(RIGHT * j * grid_size + DOWN * i * grid_size)
                grid.add(cell)

        grid.move_to(RIGHT * 1.5 + DOWN * 0.5)

        # Row labels (Q) and column labels (K)
        q_labels = VGroup()
        k_labels = VGroup()
        for i, w in enumerate(words):
            ql = Text(w, font_size=11, color=Q_COLOR)
            ql.next_to(grid[i * n], LEFT, buff=0.15)
            q_labels.add(ql)

            kl = Text(w, font_size=11, color=K_COLOR)
            kl.next_to(grid[i], UP, buff=0.15)
            kl.rotate(45 * DEGREES)
            k_labels.add(kl)

        q_axis_label = Text("Queries", font_size=14, color=Q_COLOR)
        q_axis_label.next_to(q_labels, LEFT, buff=0.3)
        k_axis_label = Text("Keys", font_size=14, color=K_COLOR)
        k_axis_label.next_to(k_labels, UP, buff=0.2)

        self.play(
            LaggedStart(
                *[FadeIn(cell, scale=0.8) for cell in grid],
                lag_ratio=0.01,
            ),
            run_time=1.5,
        )
        self.play(
            FadeIn(q_labels), FadeIn(k_labels),
            FadeIn(q_axis_label), FadeIn(k_axis_label),
        )
        self.wait(0.8)

        # ── Beat 6: Scale by sqrt(d_k) ────────────────────────
        scale_label = Text("Step 2: Scale by 1/sqrt(d_k)", font_size=22, color=GOLD)
        scale_label.move_to(step_label)

        scale_formula = Text("scores = scores / sqrt(64) = scores / 8", font_size=18, color=SOFT_WHITE)
        scale_formula.next_to(scale_label, DOWN, buff=0.3)

        scale_note = Text(
            "Prevents gradients from vanishing in softmax",
            font_size=14, color=DIM_COLOR,
        )
        scale_note.next_to(scale_formula, DOWN, buff=0.15)

        # Dim the grid slightly to show scaling
        self.play(
            Transform(step_label, scale_label),
            Transform(formula_text, scale_formula),
            grid.animate.set_opacity(0.6),
            run_time=0.8,
        )
        self.play(FadeIn(scale_note))

        # Flash the grid back brighter (scaled values)
        self.play(
            grid.animate.set_opacity(0.85),
            run_time=0.5,
        )
        self.wait(0.5)

        # ── Beat 7: Softmax — attention weights ───────────────
        softmax_label = Text("Step 3: Softmax (normalize rows)", font_size=22, color=GOLD)
        softmax_label.move_to(step_label)

        softmax_formula = Text("weights = softmax(scores)", font_size=18, color=SOFT_WHITE)
        softmax_formula.next_to(softmax_label, DOWN, buff=0.3)

        self.play(
            Transform(step_label, softmax_label),
            Transform(formula_text, softmax_formula),
            FadeOut(scale_note),
            run_time=0.6,
        )

        # Apply softmax to scores (visually: brighten high, darken low)
        softmax_vals = np.exp(score_values)
        softmax_vals = softmax_vals / softmax_vals.sum(axis=1, keepdims=True)

        animations = []
        for i in range(n):
            for j in range(n):
                val = softmax_vals[i][j]
                cell = grid[i * n + j]
                new_color = interpolate_color(BLACK, GOLD, val)
                animations.append(cell.animate.set_fill(new_color, opacity=0.9))

        self.play(*animations, run_time=1.2)

        # Add weight percentages to a few key cells
        weight_labels = VGroup()
        highlight_positions = [(0, 0), (1, 1), (2, 2)]  # Diagonal
        for i, j in highlight_positions:
            val = softmax_vals[i][j]
            wl = Text(f"{val:.0%}", font_size=9, color=WHITE)
            wl.move_to(grid[i * n + j])
            weight_labels.add(wl)

        self.play(FadeIn(weight_labels, run_time=0.5))
        self.wait(0.8)

        # ── Beat 8: Multiply by V — output ────────────────────
        output_label = Text("Step 4: Weighted sum of Values", font_size=22, color=GOLD)
        output_label.move_to(step_label)

        output_formula = Text("output = weights x V", font_size=18, color=SOFT_WHITE)
        output_formula.next_to(output_label, DOWN, buff=0.3)

        # V matrix on the right
        v_small = make_matrix_block("V", V_COLOR, width=0.9, height=1.8)
        v_small.scale(0.6)
        v_small.next_to(grid, RIGHT, buff=0.5)

        # Multiply arrow
        mult_arrow = Arrow(
            grid.get_right(), v_small.get_left(),
            color=WHITE, stroke_width=2, buff=0.1,
        )

        # Output block
        out_block = RoundedRectangle(
            width=0.9, height=1.8, corner_radius=0.1,
            fill_color=GREEN, fill_opacity=0.2,
            stroke_color=GREEN, stroke_width=2,
        ).scale(0.6)
        out_label = Text("Output", font_size=14, color=GREEN)
        out_label.move_to(out_block)
        out_group = VGroup(out_block, out_label)
        out_group.next_to(v_small, RIGHT, buff=0.5)

        equals_arrow = Arrow(
            v_small.get_right(), out_group.get_left(),
            color=WHITE, stroke_width=2, buff=0.1,
        )

        self.play(
            Transform(step_label, output_label),
            Transform(formula_text, output_formula),
            run_time=0.6,
        )
        self.play(
            GrowArrow(mult_arrow),
            FadeIn(v_small, shift=LEFT * 0.3),
            run_time=0.6,
        )
        self.play(
            GrowArrow(equals_arrow),
            FadeIn(out_group, shift=LEFT * 0.3),
            run_time=0.6,
        )
        self.wait(0.5)

        # ── Beat 9: Final summary equation ─────────────────────
        self.play(
            FadeOut(q_labels), FadeOut(k_labels),
            FadeOut(q_axis_label), FadeOut(k_axis_label),
            FadeOut(weight_labels), FadeOut(qkv_group),
            run_time=0.5,
        )

        final_eq = Text(
            "Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V",
            font_size=24, color=WHITE,
        )
        final_eq.to_edge(DOWN, buff=0.5)

        box = SurroundingRectangle(final_eq, color=GOLD, buff=0.2, corner_radius=0.1)

        self.play(Write(final_eq, run_time=1.2))
        self.play(Create(box))

        # Pulse highlight
        self.play(
            box.animate.set_stroke(width=4),
            rate_func=there_and_back,
            run_time=0.8,
        )
        self.wait(2)
