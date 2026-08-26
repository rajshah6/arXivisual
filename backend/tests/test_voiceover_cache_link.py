"""Tests for the runner-side persistent voiceover cache and concurrency parse."""


from jobs.worker import parse_render_concurrency
from rendering.local_runner import _link_persistent_voiceover_cache


class TestVoiceoverCacheLink:
    def test_symlinks_default_cache_to_persistent_per_scene_dir(self, tmp_path, monkeypatch):
        cache_root = tmp_path / "persist"
        monkeypatch.setenv("VOICEOVER_CACHE_DIR", str(cache_root))
        media = tmp_path / "render" / "media"

        _link_persistent_voiceover_cache(media, "AttentionScene")

        link = media / "voiceovers"
        assert link.is_symlink()
        assert link.resolve() == (cache_root / "AttentionScene").resolve()
        # Writes through manim-voiceover's default Path(media)/"voiceovers"
        # land in the persistent target and survive the tmpdir's deletion.
        (link / "cache.json").write_text("{}")
        assert (cache_root / "AttentionScene" / "cache.json").read_text() == "{}"

    def test_scene_name_is_sanitized_for_filesystem(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VOICEOVER_CACHE_DIR", str(tmp_path / "persist"))
        media = tmp_path / "media"
        _link_persistent_voiceover_cache(media, "Weird/Scene:Name!")
        target = (media / "voiceovers").resolve()
        assert target.name == "Weird_Scene_Name_"

    def test_distinct_scenes_get_distinct_caches(self, tmp_path, monkeypatch):
        # Per-scene isolation is what prevents concurrent renders from racing
        # on a shared cache.json index.
        monkeypatch.setenv("VOICEOVER_CACHE_DIR", str(tmp_path / "persist"))
        media_a, media_b = tmp_path / "a" / "media", tmp_path / "b" / "media"
        _link_persistent_voiceover_cache(media_a, "SceneA")
        _link_persistent_voiceover_cache(media_b, "SceneB")
        assert (media_a / "voiceovers").resolve() != (media_b / "voiceovers").resolve()

    def test_failure_is_non_fatal(self, tmp_path, monkeypatch):
        # Point the cache root at a path that cannot be created (a file).
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        monkeypatch.setenv("VOICEOVER_CACHE_DIR", str(blocker))
        media = tmp_path / "media"
        _link_persistent_voiceover_cache(media, "Scene")  # must not raise
        assert not (media / "voiceovers").exists() or not (media / "voiceovers").is_symlink()


class TestParseRenderConcurrency:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("RENDER_CONCURRENCY", raising=False)
        assert parse_render_concurrency() == 3

    def test_valid_value(self, monkeypatch):
        monkeypatch.setenv("RENDER_CONCURRENCY", "2")
        assert parse_render_concurrency() == 2

    def test_non_numeric_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RENDER_CONCURRENCY", "many")
        assert parse_render_concurrency() == 3

    def test_empty_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RENDER_CONCURRENCY", "")
        assert parse_render_concurrency() == 3

    def test_floor_of_one(self, monkeypatch):
        monkeypatch.setenv("RENDER_CONCURRENCY", "0")
        assert parse_render_concurrency() == 1
