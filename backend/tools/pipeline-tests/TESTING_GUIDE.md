# Video Generation Testing Guide

This guide explains how to test the video generation pipeline independently from the full paper processing workflow.

## Quick Start

### 1. Quick Render (Fastest)
Render a single Manim code file directly:

```bash
python quick_render.py examples/voiceover_equation.py
```

With options:
```bash
# High quality rendering
python quick_render.py examples/voiceover_equation.py --quality high_quality

# Verbose output for debugging
python quick_render.py examples/voiceover_equation.py -v

# Specify a scene name
python quick_render.py examples/voiceover_equation.py --scene MyScene
```

**When to use:** Testing individual Manim code files, quick iterations on visualization code.

---

### 2. Test Video Generation Only
Render Manim code (from file or string) without ingesting a paper:

```bash
# From a code file
python test_video_generation.py --code-file examples/voiceover_equation.py

# From inline code
python test_video_generation.py --code "class TestScene(Scene): ..."

# With quality option
python test_video_generation.py --code-file examples/voiceover_equation.py --quality low_quality

# Keep temporary files for inspection
python test_video_generation.py --code-file examples/voiceover_equation.py --keep-temp
```

**When to use:** Testing code validation and rendering without the full pipeline. Useful for debugging render failures.

---

### 3. Test Pipeline Steps
Test individual pipeline phases or the complete pipeline:

```bash
# Test just paper ingestion
python test_pipeline_steps.py --arxiv-id 2410.05905 --step ingest

# Test visualization generation
python test_pipeline_steps.py --arxiv-id 2410.05905 --step generate

# Run complete pipeline
python test_pipeline_steps.py --arxiv-id 2410.05905 --step all

# Limit visualizations
python test_pipeline_steps.py --arxiv-id 2410.05905 --step all --max-viz 1
```

Available steps:
- `ingest` - Fetch and parse paper from arXiv
- `generate` - Generate visualizations from paper
- `render` - Render videos (requires visualizations)
- `all` - Run complete pipeline

**When to use:** Testing the full pipeline with a real paper, debugging issues at specific stages.

---

## Typical Testing Workflows

### Workflow 1: Quick Iteration on Manim Code
```bash
# 1. Edit your code in examples/my_scene.py
# 2. Test render
python quick_render.py examples/my_scene.py

# 3. If it fails, debug the error
# 4. Repeat from step 1
```

### Workflow 2: Validating Generated Code
```bash
# 1. Generate visualizations for a paper
python test_pipeline_steps.py --arxiv-id 2410.05905 --step generate

# 2. Grab the generated Manim code (from logs or database)
# 3. Save it to a file: generated_code.py
# 4. Test render
python test_video_generation.py --code-file generated_code.py

# 5. If render fails, debug and iterate
```

### Workflow 3: Full Pipeline Testing
```bash
# Test complete pipeline with a paper
python test_pipeline_steps.py --arxiv-id 2410.05905 --step all

# Monitor progress through all stages:
# - Paper ingestion
# - Visualization generation
# - Video rendering
```

### Workflow 4: Testing API Render Endpoint
```bash
# Use the /api/render endpoint directly
curl -X POST http://localhost:8000/api/render \
  -H "Content-Type: application/json" \
  -d '{
    "code": "class MyScene(Scene): ...",
    "quality": "low_quality"
  }'
```

---

## Environment Setup

Make sure you have:

1. **Python dependencies** installed:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Manim installed** and accessible:
   ```bash
   manim --version  # Should show version info
   ```

3. **.env file configured** with required API keys:
   ```bash
   cp .env.example .env
   # Fill in OPENAI_API_KEY, ELEVENLABS_API_KEY, etc.
   ```

4. **Database initialized** (if testing full pipeline):
   ```bash
   python -c "from db import init_db; asyncio.run(init_db())"
   ```

---

## Configuration Options

### Quality Presets

| Quality | Rendering Time | Use Case |
|---------|-----------------|----------|
| `low_quality` | ~10-30s | Development, quick tests |
| `medium_quality` | ~1-2 min | Testing, demos |
| `high_quality` | ~5-10 min | Production, final videos |

### Logging Levels

Set logging level via environment:
```bash
LOGLEVEL=DEBUG python quick_render.py examples/voiceover_equation.py
```

Or modify the scripts to change `logging.basicConfig(level=...)`.

---

## Common Issues

### Issue: "No module named 'rendering'"
**Solution:** Make sure you're running from the `backend/` directory:
```bash
cd backend
python test_video_generation.py --code-file examples/voiceover_equation.py
```

### Issue: "manim: command not found"
**Solution:** Install Manim:
```bash
pip install manim
# Or if you prefer the community version:
pip install manim-community
```

### Issue: Render fails with "Scene not found"
**Solution:** Specify the scene name explicitly:
```bash
python quick_render.py examples/voiceover_equation.py --scene MyScene
```

### Issue: "API key not found" error
**Solution:** Add keys to `.env`:
```bash
echo "OPENAI_API_KEY=sk-..." >> .env
echo "ELEVENLABS_API_KEY=..." >> .env
```

### Issue: Out of memory during rendering
**Solution:** Use lower quality preset:
```bash
python quick_render.py examples/voiceover_equation.py --quality low_quality
```

---

## Output Files

Generated videos are typically stored in:
- **Local mode:** `generated_output/` or specified in `.env` (RENDER_OUTPUT_DIR)
- **Cloud mode:** Uploaded to Cloudflare R2 (configured via STORAGE_MODE=r2)

Video files are named: `{viz_id}.mp4`

---

## Debugging Tips

### 1. Enable Verbose Logging
```bash
python quick_render.py examples/voiceover_equation.py -v
```

### 2. Keep Temporary Files
```bash
python test_video_generation.py --code-file examples/voiceover_equation.py --keep-temp
```

### 3. Test Code Validation Only
```python
from agents.code_validator import CodeValidator
validator = CodeValidator()
result = validator.validate(your_code)
print(result.issues_found)
```

### 4. Check Manim Directly
```bash
manim -ql examples/voiceover_equation.py MyScene
```

### 5. Inspect Database Records
```python
from db.connection import async_session_maker
from db import queries

async def check_viz():
    async with async_session_maker() as db:
        viz = await queries.get_visualization(db, "viz_id")
        print(viz.manim_code)

asyncio.run(check_viz())
```

---

## Performance Tips

1. **Use `low_quality` for testing** - much faster
2. **Limit max visualizations** when testing:
   ```bash
   python test_pipeline_steps.py --arxiv-id 2410.05905 --step all --max-viz 1
   ```
3. **Test render separately** from generation:
   ```bash
   # First generate
   python test_pipeline_steps.py --arxiv-id 2410.05905 --step generate
   # Then render only problematic ones
   ```

---

## Next Steps

- **Success?** Add the paper to the database or integrate with the full pipeline
- **Issues?** Check the logs for specific error messages and stack traces
- **Optimization?** Profile the slow steps and consider parallelization options

For more info on the pipeline architecture, see [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md).
