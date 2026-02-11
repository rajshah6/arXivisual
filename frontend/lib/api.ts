/**
 * API client for communicating with the ArXiviz backend (Team 3).
 *
 * Supports toggling between mock data and real API via environment variable.
 */

import { DEMO_PAPER_IDS, getDemoPaper, MOCK_PAPER, MOCK_STATUS } from "./mock-data";
import type { Paper, ProcessingStatus, Section } from "./types";

// Toggle between mock and real API
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "true";

// Backend API base URL - defaults to localhost:8000 for development
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// === Types matching backend schemas ===

export type JobStatus = "queued" | "processing" | "completed" | "failed";
export type VisualizationStatus = "pending" | "rendering" | "complete" | "failed";

export interface ProcessResponse {
  job_id: string;
  arxiv_id: string;
  status: JobStatus;
  message: string;
}

export interface StatusResponse {
  job_id: string;
  arxiv_id: string;
  status: JobStatus;
  progress: number; // 0-100
  current_step?: string;
  sections_completed: number;
  sections_total: number;
  error?: string;
  created_at: string;
  estimated_completion?: string;
}

export interface SectionResponse {
  id: string;
  title: string;
  content: string;
  summary?: string;
  level: number;
  order_index: number;
  equations: string[];
}

export interface VisualizationResponse {
  id: string;
  section_id: string;
  concept: string;
  video_url?: string;
  status: VisualizationStatus;
}

export interface PaperResponse {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  pdf_url: string;
  html_url?: string;
  sections: SectionResponse[];
  visualizations: VisualizationResponse[];
  processed_at: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  services: Record<string, string>;
}

// === Helpers ===

/**
 * Resolve a video URL: absolute URLs (from R2 cloud) pass through,
 * relative URLs (from local backend) get prefixed with API_BASE.
 */
function resolveVideoUrl(url: string | undefined | null): string | undefined {
  if (!url) return undefined;
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return url;
  }
  return `${API_BASE}${url}`;
}

// === API Functions ===

/**
 * Start processing an arXiv paper.
 * Returns a job_id that can be polled for status.
 */
export async function processArxivPaper(arxivId: string): Promise<ProcessResponse> {
  if (USE_MOCK) {
    // Simulate API delay
    await new Promise((r) => setTimeout(r, 500));
    return {
      job_id: "mock-job-" + Date.now(),
      arxiv_id: arxivId,
      status: "queued",
      message: "Processing started (mock mode)",
    };
  }

  const res = await fetch(`${API_BASE}/api/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arxiv_id: arxivId }),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to start processing: ${res.status} - ${errorText}`);
  }

  return res.json();
}

/**
 * Poll the processing status of a job.
 */
export async function getProcessingStatus(jobId: string): Promise<StatusResponse> {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 300));
    return {
      job_id: jobId,
      arxiv_id: MOCK_STATUS.job_id,
      status: MOCK_STATUS.status as JobStatus,
      progress: Math.round(MOCK_STATUS.progress * 100),
      current_step: MOCK_STATUS.current_step,
      sections_completed: MOCK_STATUS.sections_completed,
      sections_total: MOCK_STATUS.sections_total,
      created_at: new Date().toISOString(),
    };
  }

  const res = await fetch(`${API_BASE}/api/status/${encodeURIComponent(jobId)}`);

  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(`Job not found: ${jobId}`);
    }
    const errorText = await res.text();
    throw new Error(`Failed to get status: ${res.status} - ${errorText}`);
  }

  return res.json();
}

/**
 * Get a processed paper with all sections and visualizations.
 * Returns null if paper hasn't been processed yet (404).
 */
export async function getPaper(arxivId: string): Promise<Paper | null> {
  // Demo paper fast path — always works, no backend needed
  const demoPaper = getDemoPaper(arxivId);
  if (demoPaper) {
    return demoPaper;
  }

  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 400));
    return {
      ...MOCK_PAPER,
      paper_id: arxivId,
    };
  }

  const res = await fetch(`${API_BASE}/api/paper/${encodeURIComponent(arxivId)}`);

  if (res.status === 404) {
    return null; // Paper not processed yet
  }

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to get paper: ${res.status} - ${errorText}`);
  }

  const data: PaperResponse = await res.json();

  // Convert backend response to frontend Paper type
  // Map visualizations to their corresponding sections
  const vizBySectionId = new Map<string, VisualizationResponse>();
  for (const viz of data.visualizations) {
    // If there are multiple visualizations per section, take the first complete one
    const existing = vizBySectionId.get(viz.section_id);
    if (!existing || (viz.status === "complete" && existing.status !== "complete")) {
      vizBySectionId.set(viz.section_id, viz);
    }
  }

  const sections: Section[] = data.sections.map((s) => {
    const viz = vizBySectionId.get(s.id);
    return {
      id: s.id,
      title: s.title,
      content: s.content,
      summary: s.summary || undefined,
      level: s.level,
      order_index: s.order_index,
      equations: s.equations,
      video_url: resolveVideoUrl(viz?.video_url),
    };
  });

  return {
    paper_id: data.id,
    title: data.title,
    authors: data.authors,
    abstract: data.abstract,
    pdf_url: data.pdf_url,
    html_url: data.html_url,
    sections,
  };
}

/**
 * Get the URL for a video. In the real API, this endpoint serves the video directly.
 */
export function getVideoUrl(videoId: string): string {
  if (USE_MOCK) {
    return "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4";
  }
  return `${API_BASE}/api/video/${encodeURIComponent(videoId)}`;
}

/**
 * Check the health of the backend API.
 */
export async function checkHealth(): Promise<HealthResponse> {
  if (USE_MOCK) {
    return {
      status: "healthy",
      version: "mock",
      services: {
        database: "mock",
        manim: "mock",
        redis: "mock",
      },
    };
  }

  const res = await fetch(`${API_BASE}/api/health`);

  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }

  return res.json();
}

/**
 * Convert ProcessingStatus (frontend type) from StatusResponse (backend type)
 */
export function toProcessingStatus(response: StatusResponse): ProcessingStatus {
  return {
    job_id: response.job_id,
    status: response.status,
    progress: response.progress / 100, // Backend sends 0-100, frontend expects 0-1
    sections_completed: response.sections_completed,
    sections_total: response.sections_total,
    current_step: response.current_step,
    error: response.error,
  };
}
