"""
Video storage backends for ArXivisual.

STORAGE_MODE env var controls which backend is used:
  - "local" (default): filesystem storage in ./media/videos/
  - "r2": Cloudflare R2 (S3-compatible) cloud storage
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

STORAGE_MODE = os.getenv("STORAGE_MODE", "local")


# ── Protocol ────────────────────────────────────────────────────


class StorageBackend(Protocol):
    async def save_video(self, video_bytes: bytes, filename: str) -> str: ...
    def get_video_path(self, video_id: str) -> Optional[Path]: ...
    def get_video_url(self, video_id: str) -> Optional[str]: ...
    def list_videos(self) -> list[str]: ...
    def delete_video(self, video_id: str) -> bool: ...


# ── Local Backend ───────────────────────────────────────────────


class LocalStorageBackend:
    """Stores videos on the local filesystem (development default)."""

    def __init__(self) -> None:
        self.media_dir = Path(os.getenv("MEDIA_DIR", "./media/videos"))
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def save_video(self, video_bytes: bytes, filename: str) -> str:
        if not filename.endswith(".mp4"):
            filename = f"{filename}.mp4"
        file_path = self.media_dir / filename
        file_path.write_bytes(video_bytes)
        video_id = filename.replace(".mp4", "")
        return f"/api/video/{video_id}"

    def get_video_path(self, video_id: str) -> Optional[Path]:
        file_path = self.media_dir / f"{video_id}.mp4"
        if file_path.exists():
            return file_path
        file_path = self.media_dir / video_id
        if file_path.exists():
            return file_path
        return None

    def get_video_url(self, video_id: str) -> Optional[str]:
        if self.get_video_path(video_id):
            return f"/api/video/{video_id}"
        return None

    def list_videos(self) -> list[str]:
        return sorted(f.stem for f in self.media_dir.glob("*.mp4"))

    def delete_video(self, video_id: str) -> bool:
        path = self.get_video_path(video_id)
        if path:
            path.unlink()
            return True
        return False


# ── R2 Backend ──────────────────────────────────────────────────


class R2StorageBackend:
    """Uploads videos to Cloudflare R2 (S3-compatible) and returns public URLs."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.endpoint = os.getenv("S3_ENDPOINT", "")
        self.bucket = os.getenv("S3_BUCKET", "arxiviz-videos")
        self.public_url = os.getenv("S3_PUBLIC_URL", "").rstrip("/")
        access_key = os.getenv("S3_ACCESS_KEY", "")
        secret_key = os.getenv("S3_SECRET_KEY", "")

        if not all([self.endpoint, access_key, secret_key, self.public_url]):
            raise ValueError(
                "R2 storage requires S3_ENDPOINT, S3_ACCESS_KEY, "
                "S3_SECRET_KEY, and S3_PUBLIC_URL environment variables"
            )

        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )

    def _key(self, filename: str) -> str:
        """Build the S3 object key under the videos/ prefix."""
        if not filename.endswith(".mp4"):
            filename = f"{filename}.mp4"
        return f"videos/{filename}"

    async def save_video(self, video_bytes: bytes, filename: str) -> str:
        key = self._key(filename)
        for attempt in range(2):
            try:
                await asyncio.to_thread(
                    self.client.put_object,
                    Bucket=self.bucket,
                    Key=key,
                    Body=video_bytes,
                    ContentType="video/mp4",
                    CacheControl="public, max-age=31536000",
                )
                url = f"{self.public_url}/{key}"
                logger.info("Uploaded %s to R2 -> %s", key, url)
                return url
            except Exception as e:
                if attempt == 0:
                    logger.warning("R2 upload failed, retrying: %s", e)
                    await asyncio.sleep(1)
                else:
                    raise

    def get_video_path(self, video_id: str) -> Optional[Path]:
        # Cloud storage has no local path
        return None

    def get_video_url(self, video_id: str) -> Optional[str]:
        key = self._key(video_id)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return f"{self.public_url}/{key}"
        except Exception:
            return None

    def list_videos(self) -> list[str]:
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket, Prefix="videos/"
            )
            videos = []
            for obj in response.get("Contents", []):
                name = obj["Key"].removeprefix("videos/")
                if name.endswith(".mp4"):
                    videos.append(name.removesuffix(".mp4"))
            return sorted(videos)
        except Exception as e:
            logger.error("Failed to list R2 videos: %s", e)
            return []

    def delete_video(self, video_id: str) -> bool:
        key = self._key(video_id)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error("Failed to delete %s from R2: %s", key, e)
            return False

    def check_connectivity(self) -> bool:
        """Quick R2 health check via HEAD bucket."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


# ── Module-level singleton + public API ─────────────────────────


def _create_backend() -> StorageBackend:
    if STORAGE_MODE == "r2":
        logger.info("Using R2 cloud storage backend")
        return R2StorageBackend()
    else:
        logger.info("Using local filesystem storage backend")
        return LocalStorageBackend()


_backend = _create_backend()


async def save_video(video_bytes: bytes, filename: str) -> str:
    """Save video and return its URL (relative for local, absolute for R2)."""
    return await _backend.save_video(video_bytes, filename)


def get_video_path(video_id: str) -> Optional[Path]:
    """Get local file path for a video. Returns None for cloud storage."""
    return _backend.get_video_path(video_id)


def get_video_url(video_id: str) -> Optional[str]:
    """Get the URL for a video if it exists."""
    return _backend.get_video_url(video_id)


def list_videos() -> list[str]:
    """List all video IDs in storage."""
    return _backend.list_videos()


def delete_video(video_id: str) -> bool:
    """Delete a video. Returns True if deleted, False if not found."""
    return _backend.delete_video(video_id)


def get_backend() -> StorageBackend:
    """Get the active backend instance (for health checks, etc.)."""
    return _backend
