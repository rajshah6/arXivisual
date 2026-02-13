"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Props = {
  src: string;
  title?: string;
  className?: string;
  autoPlay?: boolean;
  pauseWhenInactive?: boolean;
};

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function VideoPlayer({
  src,
  title = "Visualization video",
  className,
  autoPlay = false,
  pauseWhenInactive = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [hadError, setHadError] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const progressPct = useMemo(() => {
    if (!duration) return 0;
    return Math.max(0, Math.min(100, (currentTime / duration) * 100));
  }, [currentTime, duration]);

  useEffect(() => {
    setIsPlaying(false);
    setIsReady(false);
    setHadError(false);
    setProgress(0);
    setCurrentTime(0);
    setDuration(0);
  }, [src]);

  function togglePlay() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play();
    } else {
      v.pause();
    }
  }

  function onTimeUpdate() {
    const v = videoRef.current;
    if (!v) return;
    setCurrentTime(v.currentTime);
    setDuration(v.duration || 0);
    setProgress((v.currentTime / (v.duration || 1)) * 100);
  }

  function onSeek(e: React.MouseEvent<HTMLDivElement>) {
    const v = videoRef.current;
    if (!v || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    v.currentTime = Math.max(0, Math.min(duration, pct * duration));
  }

  async function toggleFullscreen() {
    const container = containerRef.current;
    const video = videoRef.current;
    if (!container || !video) return;

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }
      if (container.requestFullscreen) {
        await container.requestFullscreen();
        return;
      }
    } catch {
      // Fall back to iOS video fullscreen below.
    }

    const iosVideo = video as HTMLVideoElement & {
      webkitEnterFullscreen?: () => void;
    };
    if (typeof iosVideo.webkitEnterFullscreen === "function") {
      iosVideo.webkitEnterFullscreen();
    }
  }

  useEffect(() => {
    function onFullscreenChange() {
      const fsEl = document.fullscreenElement;
      setIsFullscreen(
        Boolean(
          fsEl &&
            (fsEl === containerRef.current || fsEl === videoRef.current)
        )
      );
    }

    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
    };
  }, []);

  useEffect(() => {
    if (!pauseWhenInactive) return;
    const v = videoRef.current;
    if (!v || v.paused) return;
    v.pause();
  }, [pauseWhenInactive]);

  if (!src) return null;

  return (
    <div
      ref={containerRef}
      className={[
        "relative overflow-hidden rounded-xl bg-black border border-white/[0.06]",
        className ?? "",
      ].join(" ")}
    >
      <video
        ref={videoRef}
        src={src}
        className="block w-full"
        playsInline
        preload="metadata"
        autoPlay={autoPlay}
        muted={autoPlay}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onLoadedData={() => setIsReady(true)}
        onLoadedMetadata={() => {
          const v = videoRef.current;
          if (!v) return;
          setDuration(v.duration || 0);
        }}
        onTimeUpdate={onTimeUpdate}
        onError={() => setHadError(true)}
      />

      {/* Overlay button */}
      <button
        type="button"
        onClick={togglePlay}
        aria-label={isPlaying ? "Pause video" : "Play video"}
        className="absolute inset-0 grid place-items-center bg-black/30 transition hover:bg-black/40"
      >
        {!isPlaying && (
          <div className="grid h-14 w-14 place-items-center rounded-full bg-white/90 text-black shadow-[0_18px_45px_-25px_rgba(0,0,0,0.9)]">
            <svg
              viewBox="0 0 24 24"
              className="h-7 w-7 translate-x-[1px]"
              fill="currentColor"
              aria-hidden
            >
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
        )}
      </button>

      {/* Top-left label */}
      <div className="pointer-events-none absolute left-3 top-3 rounded-lg bg-black/50 backdrop-blur-md px-2.5 py-1 text-[11px] text-white/60 border border-white/[0.06]">
        {title}
      </div>

      {/* Bottom gradient + controls */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/70 to-transparent" />

      <div className="absolute inset-x-3 bottom-3">
        {hadError ? (
          <div className="rounded-lg bg-[#f27066]/10 px-3 py-2 text-xs text-[#f27066] border border-[#f27066]/20">
            Couldn&apos;t load this video. The URL may be temporary or blocked.
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="rounded-md bg-black/50 backdrop-blur-sm px-2 py-1 text-[11px] text-white/60 border border-white/[0.06]">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>
            <div
              role="progressbar"
              aria-label="Video progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progressPct)}
              onClick={onSeek}
              className="group h-2 flex-1 cursor-pointer rounded-full bg-white/[0.08] border border-white/[0.06]"
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-white/50 to-white/30 transition-[width] duration-100"
                style={{ width: `${progressPct}%` }}
              />
              <div
                className="mt-1 text-[10px] text-white/30"
                style={{ display: "none" }}
              >
                {progress.toFixed(1)}%
              </div>
            </div>
            <div className="rounded-md bg-black/50 backdrop-blur-sm px-2 py-1 text-[11px] text-white/40 border border-white/[0.06]">
              {isReady ? "HD" : "Loading..."}
            </div>
            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
              className="rounded-md bg-black/50 backdrop-blur-sm px-2 py-1 text-[11px] text-white/60 border border-white/[0.06] hover:text-white transition"
            >
              {isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
