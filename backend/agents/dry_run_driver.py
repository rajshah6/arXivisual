"""Standalone dry-run executor for generated Manim scenes.

Run as a subprocess by RenderTester: executes the scene's construct() under
manim's dry_run config (animations are processed, no frames or files are
written) with all external effects stubbed out:

- TTS is replaced by a SpeechService that emits an embedded 1s silent MP3, so
  no network call or spend happens (manim-voiceover has no dry_run support of
  its own and would otherwise call the real service from construct()).
- Scene.add_sound is a no-op — it shells out to ffmpeg for mp3->wav
  conversion, which validation doesn't need.
- Subcaptions are disabled — under dry_run ``config.output_file`` stays an
  empty string (not None, so the writer's None-guard doesn't fire) and
  ``Path("").with_suffix(".srt")`` raises at finish(). Observed empirically
  against manim 0.19.

Protocol: prints DRY_RUN_OK and exits 0 on success; prints the traceback to
stderr, then DRY_RUN_FAIL, and exits 1 on a scene failure. Any exit without a
sentinel means the harness itself broke — the caller treats that as
infrastructure trouble and fails open.

Must stay importable with only stdlib + manim + manim_voiceover: it runs in a
bare subprocess with no app context.
"""

import base64
import hashlib
import sys
import traceback
from pathlib import Path

# 1 second of silence, 8kbps mono MP3 (mutagen-parseable, so
# VoiceoverTracker.duration resolves to ~1.0s without touching ffmpeg).
_SILENT_MP3 = base64.b64decode(
    """SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYyLjMuMTAwAAAAAAAAAAAAAAD/83DAAAAAAAAAAAAASW5mbwAAAA8AAAApAAAE5QAqKjAwNTU1Ojo/Pz9FRUpKSk9PVVVaWlpgYGVlZWpqb29vdXV6enp/f4WFioqKkJCVlZWamp+fn6WlqqqwsLC1tbq6usDAxcXFysrPz8/V1dra4ODg5eXq6urw8PX19fr6//8AAAAATGF2YzYyLjExAAAAAAAAAAAAAAAAJAPeAAAAAAAABOXwQw3LAAAAAAAAAAAAAAAAAP/zEMQAAAADSAAAAABMQU1FMy4xMExBTUUz//MSxA0AAANIAAAAAC4xMDBVVVVVTEFNRTMu//MQxBsAAANIAAAAADEwMFVVVVVMQU1FMy7/8xDEKAAAA0gAAAAAMTAwVVVVVUxBTUUzLv/zEMQ1AAADSAAAAAAxMDBVVVVVTEFNRTMu//MQxEIAAANIAAAAADEwMFVVVVVMQU1FMy7/8xDETwAAA0gAAAAAMTAwVVVVVVVMQU1FM//zEMRcAAADSAAAAAAuMTAwVVVVVUxBTUUz//MQxGkAAANIAAAAAC4xMDBVVVVVTEFNRTP/8xLEdgAAA0gAAAAALjEwMFVVVVVMQU1FMy7/8xDEhAAAA0gAAAAAMTAwVVVVVUxBTUUzLv/zEMSRAAADSAAAAAAxMDBVVVVVTEFNRTMu//MQxJ4AAANIAAAAADEwMFVVVVVMQU1FMy7/8xDEqwAAA0gAAAAAMTAwVVVVVUxBTUUzLv/zEMS4AAADSAAAAAAxMDBVVVVVVUxBTUUz//MQxMUAAANIAAAAAC4xMDBVVVVVTEFNRTP/8xDE0gAAA0gAAAAALjEwMFVVVVVMQU1FM//zEsTfAAADSAAAAAAuMTAwVVVVVUxBTUUzLv/zEMTtAAADSAAAAAAxMDBVVVVVTEFNRTMu//MQxPIAAANIAAAAADEwMFVVVVVMQU1FMy7/8xDE8gAAA0gAAAAAMTAwVVVVVUxBTUUzLv/zEMTyAAADSAAAAAAxMDBVVVVVTEFNRTMu//MQxPIAAANIAAAAADEwMFVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVf/zEMTyAAADSAAAAABVVVVVVVVVVVVVVVVV//MSxPEAAANIAAAAAFVVVVVVVVVVVVVVVVVV//MQxPIAAANIAAAAAFVVVVVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVf/zEMTyAAADSAAAAABVVVVVVVVVVVVVVVVV//MQxPIAAANIAAAAAFVVVVVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVf/zEMTyAAADSAAAAABVVVVVVVVVVVVVVVVV//MQxPIAAANIAAAAAFVVVVVVVVVVVVVVVVX/8xLE8QAAA0gAAAAAVVVVVVVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVf/zEMTyAAADSAAAAABVVVVVVVVVVVVVVVVV//MQxPIAAANIAAAAAFVVVVVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVf/zEMTyAAADSAAAAABVVVVVVVVVVVVVVVVV//MQxPIAAANIAAAAAFVVVVVVVVVVVVVVVVX/8xDE8gAAA0gAAAAAVVVVVVVVVVVVVVVVVQ=="""
)

SENTINEL_OK = "DRY_RUN_OK"
SENTINEL_FAIL = "DRY_RUN_FAIL"


def _prepare_manim() -> None:
    from manim import Scene, config

    config.dry_run = True
    config.disable_caching = True
    # Keep any incidental output inside the caller's tempdir cwd.
    config.media_dir = str(Path.cwd() / "media")

    Scene.add_sound = lambda self, *args, **kwargs: None

    from manim_voiceover import VoiceoverScene
    from manim_voiceover.services.base import SpeechService

    class _SilentService(SpeechService):
        def generate_from_text(self, text, cache_dir=None, path=None, **kwargs):
            name = "silent-" + hashlib.sha1(text.encode()).hexdigest()[:12] + ".mp3"
            (Path(self.cache_dir) / name).write_bytes(_SILENT_MP3)
            return {"input_text": text, "original_audio": name, "final_audio": name}

    original = VoiceoverScene.set_speech_service

    def _stubbed(self, speech_service, **kwargs):
        kwargs["create_subcaption"] = False
        original(self, _SilentService(transcription_model=None), **kwargs)

    VoiceoverScene.set_speech_service = _stubbed


def _load_scene_classes(scene_path: str) -> list[type]:
    import importlib.util

    from manim import Scene

    spec = importlib.util.spec_from_file_location("scene_under_test", scene_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scene_under_test"] = module
    spec.loader.exec_module(module)
    return [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, Scene)
        and obj.__module__ == "scene_under_test"
    ]


def main() -> int:
    scene_path = sys.argv[1]
    scene_name = sys.argv[2] if len(sys.argv) > 2 else None
    _prepare_manim()
    # BaseException, not Exception: generated code calling sys.exit() must be a
    # scene failure (fail closed), not a missing-sentinel harness fault (which
    # fails open). KeyboardInterrupt can't reach a stdin-less subprocess.
    try:
        scene_classes = _load_scene_classes(scene_path)
        if scene_name:
            scene_classes = [c for c in scene_classes if c.__name__ == scene_name] or scene_classes
        if not scene_classes:
            # Typed line so the caller's traceback parser preserves the error class.
            print("MissingSceneError: No Scene class with construct() found", file=sys.stderr)
            print(SENTINEL_FAIL)
            return 1
        scene_classes[0]().render()
    except BaseException:
        traceback.print_exc()
        print(SENTINEL_FAIL)
        return 1
    print(SENTINEL_OK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
