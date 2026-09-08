export type ProcessingStatus = {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number; // 0.0 - 1.0
  sections_completed: number;
  sections_total: number;
  current_step?: string;
  error?: string;
};

export type Paper = {
  paper_id: string; // e.g. "1706.03762"
  title: string;
  authors: string[];
  abstract: string;
  pdf_url: string;
  html_url?: string;
  sections: Section[];
};

export type PaperStatus = "ready" | "processing" | "empty";

export type PaperSummary = {
  paper_id: string; // e.g. "1706.03762"
  title: string;
  authors: string[];
  visualization_count: number; // sections with a playable video
  status: PaperStatus;
  processed_at: string; // ISO 8601 datetime string (UTC)
};

export type Section = {
  id: string;
  title: string;
  content: string;
  summary?: string;
  level: number;
  order_index: number;
  equations: string[];
  video_url?: string;
  viz_id?: string;
  videos?: SectionVideo[];
};

export type SectionVideo = {
  viz_id: string;
  video_url: string;
  concept: string;
};

