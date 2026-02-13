# Team 4: Frontend & User Experience

## Your Mission

Build the scrollytelling frontend that displays papers with embedded videos. You consume the API endpoints that Team 3 (Backend) provides.

## Overview

```
[Team 3 REST API] → Next.js App → Scrollytelling UI → Video Player → User
```

**Important**: Team 3 owns the API contract. Build against their endpoints. Coordinate on schemas early. Use mocks for parallel development.

## Files You Own

```
frontend/
├── app/
│   ├── layout.tsx                  # Root layout
│   ├── page.tsx                    # Landing page
│   ├── globals.css                 # Global styles
│   └── abs/
│       └── [...id]/
│           ├── page.tsx            # Paper display page (mirrors arXiv URL)
│           └── loading.tsx         # Loading state
├── components/
│   ├── ScrollySection.tsx          # Individual scrolling section
│   ├── VideoPlayer.tsx             # Video playback component
│   ├── LoadingState.tsx            # Processing/loading indicators
│   ├── ProgressBar.tsx             # Processing progress bar
│   ├── PaperHeader.tsx             # Paper title, authors, abstract
│   └── LandingHero.tsx             # Landing page hero section
├── lib/
│   ├── api.ts                      # Backend API client (with mock support)
│   ├── types.ts                    # TypeScript types
│   └── mock-data.ts                # Mock data for parallel development
└── hooks/
    ├── useScrollPosition.ts        # Scroll tracking hook
    ├── usePaperData.ts             # Data fetching hook
    └── useProcessingStatus.ts      # Status polling hook
```

---

## Part 1: Project Setup

### Initialize Next.js

```bash
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir=false
cd frontend
npm install framer-motion @tanstack/react-query axios
```

### Directory Structure

```bash
mkdir -p app/abs/\[...id\]
mkdir -p components lib hooks
```

---

## Part 2: Types (`lib/types.ts`)

```typescript
export interface Paper {
  paper_id: string;
  title: string;
  authors: string[];
  abstract: string;
  pdf_url: string;
  html_url?: string;
  sections: Section[];
}

export interface Section {
  id: string;
  title: string;
  content: string;
  level: number;
  order_index: number;
  equations: string[];
  video_url?: string;
}

export interface ProcessingStatus {
  job_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;  // 0.0 to 1.0
  sections_completed: number;
  sections_total: number;
  current_step?: string;
  error?: string;
}

export interface ProcessResponse {
  job_id: string;
  status: string;
  paper_id: string;
}
```

---

## Part 3: API Client (`lib/api.ts`)

### With Mock Support for Parallel Development

```typescript
import axios from 'axios';
import { Paper, ProcessingStatus, ProcessResponse } from './types';
import { MOCK_PAPER, MOCK_STATUS } from './mock-data';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true';

export const api = {
  /**
   * Start processing a paper
   */
  async processPaper(arxivId: string): Promise<ProcessResponse> {
    if (USE_MOCK) {
      return { job_id: 'mock-job-123', status: 'queued', paper_id: arxivId };
    }
    const res = await axios.post(`${API_BASE}/api/process`, { arxiv_id: arxivId });
    return res.data;
  },

  /**
   * Get processing status (for polling)
   */
  async getStatus(jobId: string): Promise<ProcessingStatus> {
    if (USE_MOCK) {
      return MOCK_STATUS;
    }
    const res = await axios.get(`${API_BASE}/api/status/${jobId}`);
    return res.data;
  },

  /**
   * Get processed paper with sections and video URLs
   */
  async getPaper(arxivId: string): Promise<Paper | null> {
    if (USE_MOCK) {
      return MOCK_PAPER;
    }
    try {
      const res = await axios.get(`${API_BASE}/api/paper/${arxivId}`);
      return res.data;
    } catch (e: any) {
      if (e.response?.status === 404) return null;
      throw e;
    }
  },

  /**
   * Get video URL
   */
  async getVideoUrl(videoId: string): Promise<string | null> {
    if (USE_MOCK) {
      return 'https://example.com/mock-video.mp4';
    }
    try {
      const res = await axios.get(`${API_BASE}/api/video/${videoId}`);
      return res.data.url;
    } catch {
      return null;
    }
  },
};
```

---

## Part 4: Mock Data (`lib/mock-data.ts`)

### For Development Without Backend

```typescript
import { Paper, ProcessingStatus } from './types';

export const MOCK_PAPER: Paper = {
  paper_id: '1706.03762',
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit'],
  abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...',
  pdf_url: 'https://arxiv.org/pdf/1706.03762',
  html_url: 'https://arxiv.org/abs/1706.03762',
  sections: [
    {
      id: 'section-1',
      title: 'Introduction',
      content: 'Recurrent neural networks, long short-term memory and gated recurrent neural networks in particular, have been firmly established as state of the art approaches in sequence modeling and transduction problems such as language modeling and machine translation.',
      level: 1,
      order_index: 0,
      equations: [],
      video_url: undefined,
    },
    {
      id: 'section-2',
      title: 'Model Architecture',
      content: 'Most competitive neural sequence transduction models have an encoder-decoder structure. The encoder maps an input sequence to a sequence of continuous representations.',
      level: 1,
      order_index: 1,
      equations: ['Attention(Q, K, V) = softmax(QK^T / sqrt(d_k))V'],
      video_url: 'https://example.com/attention-visualization.mp4',
    },
    {
      id: 'section-3',
      title: 'Multi-Head Attention',
      content: 'Instead of performing a single attention function with d_model-dimensional keys, values and queries, we found it beneficial to linearly project the queries, keys and values h times with different, learned linear projections.',
      level: 2,
      order_index: 2,
      equations: ['MultiHead(Q, K, V) = Concat(head_1, ..., head_h)W^O'],
      video_url: 'https://example.com/multihead-visualization.mp4',
    },
  ],
};

export const MOCK_STATUS: ProcessingStatus = {
  job_id: 'mock-job-123',
  status: 'completed',
  progress: 1.0,
  sections_completed: 3,
  sections_total: 3,
  current_step: 'Complete',
};

// Simulated progressive status for testing loading states
export function getMockProgressiveStatus(elapsedMs: number): ProcessingStatus {
  const steps = [
    { step: 'Fetching paper from arXiv', progress: 0.1 },
    { step: 'Parsing document structure', progress: 0.3 },
    { step: 'Generating visualizations', progress: 0.5 },
    { step: 'Rendering videos', progress: 0.8 },
    { step: 'Complete', progress: 1.0 },
  ];

  const stepIndex = Math.min(Math.floor(elapsedMs / 2000), steps.length - 1);
  const currentStep = steps[stepIndex];

  return {
    job_id: 'mock-job-123',
    status: stepIndex === steps.length - 1 ? 'completed' : 'processing',
    progress: currentStep.progress,
    sections_completed: Math.floor(currentStep.progress * 3),
    sections_total: 3,
    current_step: currentStep.step,
  };
}
```

---

## Part 5: Custom Hooks

### `hooks/usePaperData.ts`

```typescript
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { Paper, ProcessingStatus } from '@/lib/types';

interface UsePaperDataResult {
  paper: Paper | null;
  status: ProcessingStatus | null;
  loading: boolean;
  error: string | null;
}

export function usePaperData(arxivId: string): UsePaperDataResult {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let pollInterval: NodeJS.Timeout | null = null;

    async function loadPaper() {
      try {
        // Try to get cached paper first
        const cached = await api.getPaper(arxivId);

        if (cached && cached.sections.some(s => s.video_url)) {
          setPaper(cached);
          setLoading(false);
          return;
        }

        // Start processing
        const { job_id } = await api.processPaper(arxivId);

        // Poll for status
        pollInterval = setInterval(async () => {
          const currentStatus = await api.getStatus(job_id);
          setStatus(currentStatus);

          if (currentStatus.status === 'completed') {
            if (pollInterval) clearInterval(pollInterval);
            const paper = await api.getPaper(arxivId);
            setPaper(paper);
            setLoading(false);
          } else if (currentStatus.status === 'failed') {
            if (pollInterval) clearInterval(pollInterval);
            setError(currentStatus.error || 'Processing failed');
            setLoading(false);
          }
        }, 2000);  // Poll every 2 seconds

      } catch (e: any) {
        setError(e.message || 'Failed to load paper');
        setLoading(false);
      }
    }

    loadPaper();

    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [arxivId]);

  return { paper, status, loading, error };
}
```

### `hooks/useScrollPosition.ts`

```typescript
'use client';

import { useState, useEffect, RefObject } from 'react';

export function useScrollPosition(containerRef: RefObject<HTMLElement>) {
  const [activeSection, setActiveSection] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const sections = container.querySelectorAll('[data-section-id]');

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

        const topSection = visible[0]?.target as HTMLElement;
        const sectionId = topSection?.dataset.sectionId;

        if (sectionId) {
          setActiveSection(sectionId);
        }
      },
      {
        root: null,
        threshold: [0.25, 0.5, 0.75],
      }
    );

    sections.forEach((section) => observer.observe(section));

    return () => observer.disconnect();
  }, [containerRef]);

  return activeSection;
}
```

### `hooks/useProcessingStatus.ts`

```typescript
'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { ProcessingStatus } from '@/lib/types';

export function useProcessingStatus(jobId: string | null) {
  const [status, setStatus] = useState<ProcessingStatus | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const pollInterval = setInterval(async () => {
      const currentStatus = await api.getStatus(jobId);
      setStatus(currentStatus);

      if (currentStatus.status === 'completed' || currentStatus.status === 'failed') {
        clearInterval(pollInterval);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [jobId]);

  return status;
}
```

---

## Part 6: Components

### `components/ScrollySection.tsx`

```typescript
'use client';

import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';
import { Section } from '@/lib/types';
import { VideoPlayer } from './VideoPlayer';

interface Props {
  section: Section;
}

export function ScrollySection({ section }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: '-100px' });

  return (
    <motion.section
      ref={ref}
      data-section-id={section.id}
      initial={{ opacity: 0, y: 50 }}
      animate={isInView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      className="mb-16"
    >
      {/* Section Header */}
      <h2
        className={`font-bold mb-4 ${
          section.level === 1 ? 'text-3xl' :
          section.level === 2 ? 'text-2xl' : 'text-xl'
        }`}
      >
        {section.title}
      </h2>

      {/* Visualization Video (if available) */}
      {section.video_url && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={isInView ? { opacity: 1, scale: 1 } : {}}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="my-8"
        >
          <div className="bg-gray-800 rounded-lg p-4">
            <VideoPlayer src={section.video_url} />
          </div>
        </motion.div>
      )}

      {/* Section Content */}
      <div className="prose prose-invert prose-lg max-w-none">
        <p className="text-gray-300 leading-relaxed">{section.content}</p>
      </div>

      {/* Equations */}
      {section.equations.length > 0 && (
        <div className="my-6 space-y-4">
          {section.equations.map((eq, i) => (
            <div
              key={i}
              className="bg-gray-800 p-4 rounded-lg overflow-x-auto"
            >
              <code className="text-blue-300 text-lg">{eq}</code>
            </div>
          ))}
        </div>
      )}
    </motion.section>
  );
}
```

### `components/VideoPlayer.tsx`

```typescript
'use client';

import { useRef, useState } from 'react';
import { motion } from 'framer-motion';

interface Props {
  src: string;
}

export function VideoPlayer({ src }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      const progress = (videoRef.current.currentTime / videoRef.current.duration) * 100;
      setProgress(progress);
    }
  };

  return (
    <div className="relative rounded-lg overflow-hidden bg-black">
      <video
        ref={videoRef}
        src={src}
        className="w-full"
        loop
        playsInline
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onTimeUpdate={handleTimeUpdate}
      />

      {/* Play/Pause overlay */}
      <motion.button
        onClick={togglePlay}
        className="absolute inset-0 flex items-center justify-center bg-black/30 hover:bg-black/40 transition-colors"
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
      >
        {!isPlaying && (
          <div className="w-16 h-16 bg-white/90 rounded-full flex items-center justify-center">
            <svg className="w-8 h-8 text-black ml-1" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
        )}
      </motion.button>

      {/* Progress bar */}
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-700">
        <div
          className="h-full bg-blue-500 transition-all duration-100"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
```

### `components/LoadingState.tsx`

```typescript
'use client';

import { motion } from 'framer-motion';
import { ProcessingStatus } from '@/lib/types';
import { ProgressBar } from './ProgressBar';

interface Props {
  status: ProcessingStatus | null;
}

export function LoadingState({ status }: Props) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-900 to-black flex items-center justify-center">
      <div className="max-w-md w-full px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center"
        >
          {/* Animated spinner */}
          <div className="mb-8">
            <motion.div
              className="w-20 h-20 mx-auto border-4 border-blue-500 border-t-transparent rounded-full"
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            />
          </div>

          <h2 className="text-2xl font-bold text-white mb-2">
            Generating Visualizations
          </h2>

          {status && (
            <>
              <p className="text-gray-400 mb-6">
                {status.current_step || 'Starting...'}
              </p>

              <ProgressBar progress={status.progress * 100} />

              <p className="text-sm text-gray-500 mt-4">
                {Math.round(status.progress * 100)}% complete
              </p>

              {status.sections_total > 0 && (
                <p className="text-xs text-gray-600 mt-2">
                  {status.sections_completed} / {status.sections_total} sections processed
                </p>
              )}
            </>
          )}
        </motion.div>
      </div>
    </div>
  );
}
```

### `components/ProgressBar.tsx`

```typescript
'use client';

import { motion } from 'framer-motion';

interface Props {
  progress: number;  // 0 to 100
}

export function ProgressBar({ progress }: Props) {
  return (
    <div className="w-full bg-gray-700 rounded-full h-2">
      <motion.div
        className="bg-blue-500 h-2 rounded-full"
        initial={{ width: 0 }}
        animate={{ width: `${progress}%` }}
        transition={{ duration: 0.5 }}
      />
    </div>
  );
}
```

### `components/PaperHeader.tsx`

```typescript
import { Paper } from '@/lib/types';

interface Props {
  paper: Paper;
}

export function PaperHeader({ paper }: Props) {
  return (
    <header className="border-b border-gray-800 py-12">
      <div className="max-w-4xl mx-auto px-6">
        <h1 className="text-4xl font-bold mb-4">{paper.title}</h1>

        <p className="text-gray-400 mb-6">
          {paper.authors.join(', ')}
        </p>

        <p className="text-gray-300 leading-relaxed">
          {paper.abstract}
        </p>

        <div className="mt-6 flex gap-4">
          <a
            href={paper.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
          >
            View PDF
          </a>
          {paper.html_url && (
            <a
              href={paper.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors"
            >
              View on arXiv
            </a>
          )}
        </div>
      </div>
    </header>
  );
}
```

---

## Part 7: Pages

### `app/layout.tsx`

```typescript
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'ArXiviz - Research Papers Visualized',
  description: 'Transform arXiv papers into interactive visual experiences',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-900 text-white`}>
        {children}
      </body>
    </html>
  );
}
```

### `app/page.tsx` (Landing Page)

```typescript
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';

export default function HomePage() {
  const [arxivUrl, setArxivUrl] = useState('');
  const router = useRouter();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Extract arXiv ID from URL
    const match = arxivUrl.match(/arxiv\.org\/abs\/([0-9.]+)/);
    if (match) {
      router.push(`/abs/${match[1]}`);
    } else if (/^[0-9.]+$/.test(arxivUrl.trim())) {
      // Direct ID input
      router.push(`/abs/${arxivUrl.trim()}`);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-900 to-black flex items-center justify-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-2xl w-full px-6 text-center"
      >
        <h1 className="text-5xl font-bold mb-4">
          ArXi<span className="text-blue-500">viz</span>
        </h1>

        <p className="text-xl text-gray-400 mb-8">
          Transform research papers into interactive visual experiences
        </p>

        <form onSubmit={handleSubmit} className="flex gap-4">
          <input
            type="text"
            value={arxivUrl}
            onChange={(e) => setArxivUrl(e.target.value)}
            placeholder="Paste arXiv URL or ID (e.g., 1706.03762)"
            className="flex-1 px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-blue-500 transition-colors"
          />
          <button
            type="submit"
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            Visualize
          </button>
        </form>

        <p className="text-sm text-gray-500 mt-4">
          Try: <span className="text-gray-400">1706.03762</span> (Attention Is All You Need)
        </p>
      </motion.div>
    </main>
  );
}
```

### `app/abs/[...id]/page.tsx` (Paper Display)

```typescript
'use client';

import { useParams } from 'next/navigation';
import { usePaperData } from '@/hooks/usePaperData';
import { PaperHeader } from '@/components/PaperHeader';
import { ScrollySection } from '@/components/ScrollySection';
import { LoadingState } from '@/components/LoadingState';

export default function PaperPage() {
  const params = useParams();
  const arxivId = Array.isArray(params.id) ? params.id.join('/') : params.id || '';

  const { paper, status, loading, error } = usePaperData(arxivId);

  if (loading) {
    return <LoadingState status={status} />;
  }

  if (error || !paper) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-red-500">Failed to load paper</h1>
          <p className="mt-2 text-gray-400">{error || 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white">
      <PaperHeader paper={paper} />

      <div className="max-w-4xl mx-auto px-6 py-12">
        {paper.sections
          .sort((a, b) => a.order_index - b.order_index)
          .map((section) => (
            <ScrollySection key={section.id} section={section} />
          ))}
      </div>
    </main>
  );
}
```

### `app/abs/[...id]/loading.tsx`

```typescript
import { LoadingState } from '@/components/LoadingState';

export default function Loading() {
  return <LoadingState status={null} />;
}
```

---

## Part 8: Environment Variables

### `.env.local`

```
# API URL (Team 3's backend)
NEXT_PUBLIC_API_URL=http://localhost:8000

# Set to 'true' to use mock data (for parallel development)
NEXT_PUBLIC_USE_MOCK=false
```

---

## Part 9: Testing

### Run Development Server

```bash
cd frontend
npm run dev
# Visit http://localhost:3000
```

### Test with Mock Data

```bash
# Enable mocks for development without backend
NEXT_PUBLIC_USE_MOCK=true npm run dev
```

### Test Paper Page

```
http://localhost:3000/abs/1706.03762
```

---

## Part 10: Design Requirements

### URL Structure
- `/` - Landing page with search
- `/abs/{paper_id}` - Paper display (mirrors arXiv URL structure)

### Features
- Progressive loading: Display sections as they complete
- Keyboard navigation: Arrow keys to navigate sections
- Dark/light mode toggle (stretch goal)
- Responsive design for mobile

### Visual Style
- Dark theme with gradient backgrounds
- Smooth scroll animations with Framer Motion
- Clean typography with good contrast

---

## Integration with Team 3

### API Contract

Team 3 provides these endpoints:

```
POST /api/process          # Start processing
  Request:  { "arxiv_id": "1706.03762" }
  Response: { "job_id": "uuid", "status": "queued", "paper_id": "1706.03762" }

GET /api/status/{job_id}   # Poll for progress
  Response: { "job_id": "uuid", "status": "processing",
              "progress": 0.6, "sections_completed": 3, "sections_total": 5 }

GET /api/paper/{arxiv_id}  # Get final result
  Response: { "paper_id": "...", "title": "...", "sections": [...] }
```

### Parallel Development Strategy

1. **Day 1**: Coordinate with Team 3 on exact response schemas
2. **Days 1-3**: Build with `NEXT_PUBLIC_USE_MOCK=true`
3. **Day 3-4**: Integration - switch to real API

---

## Handoff Checklist

- [ ] All components implemented
- [ ] Mock data works end-to-end
- [ ] API client ready to switch to real endpoints
- [ ] Responsive design tested
- [ ] Loading states and error handling complete
- [ ] Integration tested with Team 3's API
