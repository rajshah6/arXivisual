# Manim Patterns & Examples

This document contains patterns and examples for generating high-quality Manim visualizations. Use these as few-shot examples when prompting the AI to generate Manim code.

## Manim Basics

### Import and Scene Structure

```python
from manim import *

class MyScene(Scene):
    def construct(self):
        # All animation code goes here
        pass
```

### Key Concepts

- **Mobjects**: Everything visible is a Mobject (Mathematical Object)
- **Animations**: Transform Mobjects over time
- **self.play()**: Run an animation
- **self.wait()**: Pause for a duration
- **self.add()**: Add without animation

---

## Pattern 1: Equation Walkthrough

Show an equation step-by-step, highlighting parts as you explain.

```python
from manim import *

class EquationWalkthrough(Scene):
    def construct(self):
        # Title
        title = Text("Understanding the Softmax Function", font_size=36)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))
        
        # Main equation
        equation = MathTex(
            r"\text{softmax}(x_i) = ",
            r"\frac{e^{x_i}}",
            r"{\sum_{j} e^{x_j}}"
        )
        self.play(Write(equation))
        self.wait()
        
        # Highlight numerator
        self.play(equation[1].animate.set_color(YELLOW))
        
        numerator_label = Text("Exponential of input", font_size=24, color=YELLOW)
        numerator_label.next_to(equation[1], UP)
        self.play(FadeIn(numerator_label))
        self.wait()
        self.play(FadeOut(numerator_label))
        
        # Highlight denominator
        self.play(
            equation[1].animate.set_color(WHITE),
            equation[2].animate.set_color(BLUE)
        )
        
        denom_label = Text("Sum normalizes to 1", font_size=24, color=BLUE)
        denom_label.next_to(equation[2], DOWN)
        self.play(FadeIn(denom_label))
        self.wait()
        
        # Show result property
        result = MathTex(r"\sum_i \text{softmax}(x_i) = 1", color=GREEN)
        result.next_to(equation, DOWN, buff=1)
        self.play(Write(result))
        self.play(Circumscribe(result, color=GREEN))
        self.wait(2)
```

---

## Pattern 2: Architecture Diagram

Visualize a neural network or system architecture.

```python
from manim import *

class TransformerArchitecture(Scene):
    def construct(self):
        title = Text("Transformer Encoder Block", font_size=36)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create blocks
        def create_block(text, color):
            rect = RoundedRectangle(
                width=3, height=0.8, 
                corner_radius=0.1, 
                fill_color=color, 
                fill_opacity=0.3,
                stroke_color=color
            )
            label = Text(text, font_size=20)
            label.move_to(rect)
            return VGroup(rect, label)
        
        # Components
        input_embed = create_block("Input Embedding", BLUE)
        pos_encoding = create_block("+ Positional Encoding", TEAL)
        attention = create_block("Multi-Head Attention", ORANGE)
        add_norm1 = create_block("Add & Norm", GRAY)
        ffn = create_block("Feed Forward", PURPLE)
        add_norm2 = create_block("Add & Norm", GRAY)
        output = create_block("Output", GREEN)
        
        # Stack vertically
        blocks = VGroup(
            input_embed, pos_encoding, attention, 
            add_norm1, ffn, add_norm2, output
        )
        blocks.arrange(DOWN, buff=0.3)
        blocks.move_to(ORIGIN)
        
        # Animate building the architecture
        for block in blocks:
            self.play(FadeIn(block, shift=UP * 0.3), run_time=0.5)
        
        # Add arrows
        arrows = VGroup()
        for i in range(len(blocks) - 1):
            arrow = Arrow(
                blocks[i].get_bottom(),
                blocks[i+1].get_top(),
                buff=0.1,
                color=WHITE,
                stroke_width=2
            )
            arrows.add(arrow)
        
        self.play(Create(arrows), run_time=1)
        
        # Highlight attention mechanism
        self.play(
            attention.animate.set_fill(ORANGE, opacity=0.6),
            run_time=0.5
        )
        
        attention_note = Text(
            "Self-attention enables\nparallel processing",
            font_size=18,
            color=ORANGE
        )
        attention_note.next_to(attention, RIGHT, buff=0.5)
        self.play(FadeIn(attention_note))
        self.wait(2)
```

---

## Pattern 3: Data Flow Animation

Show how data flows through a system.

```python
from manim import *

class AttentionDataFlow(Scene):
    def construct(self):
        title = Text("Attention Data Flow", font_size=32)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Input tokens
        tokens = VGroup(*[
            Square(side_length=0.6, fill_color=BLUE, fill_opacity=0.5)
            for _ in range(4)
        ])
        tokens.arrange(RIGHT, buff=0.2)
        tokens.shift(UP * 2 + LEFT * 3)
        
        token_labels = VGroup(*[
            Text(t, font_size=16).move_to(tokens[i])
            for i, t in enumerate(["The", "cat", "sat", "down"])
        ])
        
        self.play(FadeIn(tokens), Write(token_labels))
        self.wait(0.5)
        
        # Q, K, V matrices
        q_matrix = self.create_matrix("Q", BLUE).shift(LEFT * 3)
        k_matrix = self.create_matrix("K", GREEN).shift(ORIGIN)
        v_matrix = self.create_matrix("V", RED).shift(RIGHT * 3)
        
        self.play(
            FadeIn(q_matrix, shift=DOWN),
            FadeIn(k_matrix, shift=DOWN),
            FadeIn(v_matrix, shift=DOWN),
        )
        
        # Animate attention computation
        # Q @ K^T
        qk_result = Text("Q·Kᵀ", font_size=24, color=YELLOW)
        qk_result.shift(DOWN * 1.5 + LEFT * 1.5)
        
        arrow_q = Arrow(q_matrix.get_bottom(), qk_result.get_top(), color=BLUE, buff=0.1)
        arrow_k = Arrow(k_matrix.get_bottom(), qk_result.get_top(), color=GREEN, buff=0.1)
        
        self.play(Create(arrow_q), Create(arrow_k))
        self.play(FadeIn(qk_result))
        self.wait(0.5)
        
        # Softmax
        softmax_result = Text("softmax(Q·Kᵀ/√d)", font_size=20, color=ORANGE)
        softmax_result.next_to(qk_result, DOWN, buff=0.5)
        self.play(Transform(qk_result.copy(), softmax_result))
        self.wait(0.5)
        
        # Multiply by V
        final_arrow = Arrow(softmax_result.get_right(), v_matrix.get_bottom(), color=RED, buff=0.2)
        self.play(Create(final_arrow))
        
        output = Text("Attention Output", font_size=24, color=WHITE)
        output.shift(DOWN * 3)
        output_box = SurroundingRectangle(output, color=YELLOW, buff=0.2)
        
        self.play(FadeIn(output), Create(output_box))
        self.wait(2)
    
    def create_matrix(self, label, color):
        rect = Rectangle(width=1.5, height=1.2, fill_color=color, fill_opacity=0.3, stroke_color=color)
        text = Text(label, font_size=24, color=color)
        text.move_to(rect)
        return VGroup(rect, text)
```

---

## Pattern 4: Step-by-Step Algorithm

Animate an algorithm's steps.

```python
from manim import *

class AlgorithmSteps(Scene):
    def construct(self):
        title = Text("Gradient Descent", font_size=36)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create axes
        axes = Axes(
            x_range=[-3, 3, 1],
            y_range=[0, 10, 2],
            x_length=6,
            y_length=4,
            tips=False
        )
        axes.shift(DOWN * 0.5)
        
        # Loss function (parabola)
        loss_curve = axes.plot(lambda x: x**2, color=BLUE)
        loss_label = Text("Loss", font_size=20, color=BLUE)
        loss_label.next_to(loss_curve, UP + RIGHT)
        
        self.play(Create(axes), Create(loss_curve), Write(loss_label))
        
        # Starting point
        x_val = ValueTracker(2.5)
        
        dot = always_redraw(lambda: Dot(
            axes.c2p(x_val.get_value(), x_val.get_value()**2),
            color=RED
        ))
        
        self.play(FadeIn(dot))
        self.wait(0.5)
        
        # Gradient descent steps
        learning_rate = 0.3
        steps_text = Text("Step 1", font_size=24).to_corner(UL).shift(DOWN)
        self.play(Write(steps_text))
        
        for i in range(5):
            current_x = x_val.get_value()
            gradient = 2 * current_x  # d/dx of x^2
            new_x = current_x - learning_rate * gradient
            
            # Show gradient arrow
            arrow = Arrow(
                axes.c2p(current_x, current_x**2),
                axes.c2p(current_x - 0.5 * gradient, current_x**2),
                color=YELLOW,
                buff=0
            )
            
            self.play(Create(arrow), run_time=0.3)
            self.play(
                x_val.animate.set_value(new_x),
                FadeOut(arrow),
                run_time=0.5
            )
            
            new_step = Text(f"Step {i+2}", font_size=24)
            new_step.move_to(steps_text)
            self.play(Transform(steps_text, new_step), run_time=0.2)
        
        # Final state
        converged = Text("Converged!", font_size=28, color=GREEN)
        converged.next_to(dot, RIGHT, buff=0.5)
        self.play(FadeIn(converged))
        self.wait(2)
```

---

## Pattern 5: Matrix Operations

Visualize matrix multiplication or transformations.

```python
from manim import *

class MatrixMultiplication(Scene):
    def construct(self):
        title = Text("Matrix Multiplication", font_size=36)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create matrices
        matrix_a = Matrix(
            [[1, 2], [3, 4]],
            left_bracket="[",
            right_bracket="]"
        ).shift(LEFT * 3)
        
        matrix_b = Matrix(
            [[5, 6], [7, 8]],
            left_bracket="[",
            right_bracket="]"
        ).shift(RIGHT * 0)
        
        equals = MathTex("=").shift(RIGHT * 2)
        
        matrix_c = Matrix(
            [["?", "?"], ["?", "?"]],
            left_bracket="[",
            right_bracket="]"
        ).shift(RIGHT * 4)
        
        self.play(
            Write(matrix_a),
            Write(matrix_b),
            Write(equals),
            Write(matrix_c)
        )
        self.wait()
        
        # Highlight row and column
        row_highlight = SurroundingRectangle(
            matrix_a.get_rows()[0], 
            color=YELLOW, 
            buff=0.1
        )
        col_highlight = SurroundingRectangle(
            matrix_b.get_columns()[0], 
            color=YELLOW, 
            buff=0.1
        )
        
        self.play(Create(row_highlight), Create(col_highlight))
        
        # Show computation
        computation = MathTex(
            r"1 \times 5 + 2 \times 7 = 19",
            font_size=28
        ).shift(DOWN * 2)
        
        self.play(Write(computation))
        self.wait()
        
        # Update result
        new_matrix_c = Matrix(
            [[19, "?"], ["?", "?"]],
            left_bracket="[",
            right_bracket="]"
        ).shift(RIGHT * 4)
        
        self.play(Transform(matrix_c, new_matrix_c))
        self.wait(2)
```

---

## Common Mobjects Reference

### Text and Math

```python
# Regular text
text = Text("Hello World", font_size=36, color=WHITE)

# LaTeX math
math = MathTex(r"\int_0^1 x^2 dx = \frac{1}{3}")

# Colored parts
equation = MathTex(r"E", r"=", r"mc^2")
equation[0].set_color(RED)
equation[2].set_color(BLUE)
```

### Shapes

```python
circle = Circle(radius=1, color=BLUE, fill_opacity=0.5)
square = Square(side_length=2, color=RED)
rectangle = Rectangle(width=3, height=2, color=GREEN)
arrow = Arrow(LEFT, RIGHT, color=YELLOW)
line = Line(start=LEFT, end=RIGHT, color=WHITE)
dot = Dot(point=ORIGIN, color=RED)
```

### Groups and Positioning

```python
# Group objects
group = VGroup(circle, square, text)
group.arrange(RIGHT, buff=0.5)  # Horizontal
group.arrange(DOWN, buff=0.3)   # Vertical

# Position relative to screen
obj.to_edge(UP)      # Top of screen
obj.to_corner(UL)    # Upper-left corner
obj.shift(RIGHT * 2) # Move right
obj.move_to(ORIGIN)  # Center
obj.next_to(other, RIGHT, buff=0.5)  # Next to another object
```

### Common Animations

```python
# Creating
self.play(Create(circle))        # Draw shape
self.play(Write(text))           # Write text
self.play(FadeIn(obj))           # Fade in
self.play(FadeIn(obj, shift=UP)) # Fade in from below

# Transforming
self.play(obj.animate.shift(RIGHT))     # Move
self.play(obj.animate.scale(2))         # Scale
self.play(obj.animate.set_color(RED))   # Change color
self.play(Transform(obj1, obj2))        # Morph
self.play(ReplacementTransform(obj1, obj2))

# Removing
self.play(FadeOut(obj))
self.play(Uncreate(circle))

# Highlighting
self.play(Circumscribe(obj, color=YELLOW))
self.play(Indicate(obj))
self.play(Flash(obj))

# Timing
self.wait(2)  # Pause for 2 seconds
self.play(Create(circle), run_time=2)  # Animation takes 2 seconds
self.play(a1, a2, lag_ratio=0.5)  # Stagger animations
```

---

## Quality Guidelines

1. **Keep it short**: 15-45 seconds is ideal
2. **One concept per video**: Don't try to explain everything
3. **Use color meaningfully**: Consistent colors for related concepts
4. **Pace appropriately**: Use `self.wait()` to let viewers absorb
5. **Build incrementally**: Show pieces, then combine
6. **Highlight changes**: Draw attention with color or animation

---

## Common Pitfalls to Avoid

```python
# BAD: Animation reference reuse
self.play(FadeIn(obj))
self.play(FadeIn(obj))  # Error! obj already in scene

# GOOD: Use different animations or remove first
self.play(FadeIn(obj))
self.play(FadeOut(obj))
self.play(FadeIn(obj))

# BAD: Forgetting to wait
self.play(Write(text))
self.play(FadeOut(text))  # Too fast!

# GOOD: Add pauses
self.play(Write(text))
self.wait(1)
self.play(FadeOut(text))

# BAD: Complex one-liners
self.play(Transform(VGroup(*[Circle() for _ in range(10)]).arrange(RIGHT), VGroup(*[Square() for _ in range(10)]).arrange(RIGHT)))

# GOOD: Break it up
circles = VGroup(*[Circle() for _ in range(10)]).arrange(RIGHT)
squares = VGroup(*[Square() for _ in range(10)]).arrange(RIGHT)
self.play(Transform(circles, squares))
```
