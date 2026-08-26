"""Evaluate the visual QA judge against already-rendered videos.

Fetches a processed paper's videos (from the live API / R2) and runs the vision
layout judge on each, printing a per-video verdict table. Use this to calibrate
the judge on real output before turning the gate on in the pipeline.

Usage (from backend/):
    uv run python tools/visual_qa_eval.py --arxiv-id 1706.03762
    uv run python tools/visual_qa_eval.py --arxiv-id 2603.20927 \
        --api https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.visual_qa import judge_video

DEFAULT_API = "https://arxivisual-api.purplepond-ac9e2dc5.eastus2.azurecontainerapps.io"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arxiv-id", required=True)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=120) as http:
        try:
            resp = await http.get(f"{args.api}/api/paper/{args.arxiv_id}")
        except httpx.RequestError as exc:
            print(f"could not reach {args.api}: {exc}")
            return 1
        if resp.status_code != 200:
            print(f"paper {args.arxiv_id} not found ({resp.status_code})")
            return 1
        paper = resp.json()

        videos = [
            (v["id"], v["video_url"])
            for v in paper.get("visualizations", [])
            if v.get("video_url") and v.get("status") == "complete"
        ]
        if not videos:
            print("no completed videos for this paper")
            return 1

        print(f"{paper['title'][:70]}")
        print(f"judging {len(videos)} video(s)...\n")
        print(f"{'viz':<20}{'severity':<10}{'ovl':<5}{'cut':<5}{'col':<5}issues")

        defects = 0
        completed = 0
        failed = 0
        for viz_id, url in videos:
            try:
                video = await http.get(url)
            except httpx.RequestError as exc:
                failed += 1
                print(f"{viz_id:<20}download error: {exc}")
                continue
            if video.status_code != 200:
                failed += 1
                print(f"{viz_id:<20}download failed ({video.status_code})")
                continue
            verdict = await judge_video(video.content, viz_id=viz_id)
            if verdict is None:
                failed += 1
                print(f"{viz_id:<20}judge unavailable")
                continue
            completed += 1
            defects += 1 if verdict.has_defects else 0
            def flag(b):
                return "Y" if b else "-"
            print(
                f"{viz_id:<20}{verdict.severity:<10}"
                f"{flag(verdict.overlap):<5}{flag(verdict.cutoff):<5}{flag(verdict.collisions):<5}"
                f"{'; '.join(verdict.issues[:2])[:80]}"
            )

        print(f"\n{defects}/{completed} judged videos have layout defects"
              + (f" ({failed} could not be evaluated)" if failed else ""))
        return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
