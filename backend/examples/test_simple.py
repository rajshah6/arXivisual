from manim import *


class SimpleTest(Scene):
    """A simple test scene that renders quickly."""
    
    def construct(self):
        # Create a circle
        circle = Circle(color=BLUE, fill_opacity=0.5)
        
        # Create text
        text = Text("Hello ArXivisual!", font_size=36)
        text.next_to(circle, DOWN)
        
        # Animate
        self.play(Create(circle), run_time=1)
        self.play(Write(text), run_time=1)
        self.wait(0.5)
