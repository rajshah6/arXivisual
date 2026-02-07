import type { Paper, ProcessingStatus } from "./types";

/**
 * Hard-coded demo paper: "Attention Is All You Need" (1706.03762)
 *
 * 5 sections with beginner-friendly descriptions and pre-rendered
 * Manim videos from backend/few-shot/, served from public/videos/demo/.
 */

export const DEMO_PAPER_ID = "1706.03762";

export const MOCK_PAPER: Paper = {
  paper_id: DEMO_PAPER_ID,
  title: "Attention Is All You Need",
  authors: [
    "Ashish Vaswani",
    "Noam Shazeer",
    "Niki Parmar",
    "Jakob Uszkoreit",
    "Llion Jones",
    "Aidan N. Gomez",
    "Lukasz Kaiser",
    "Illia Polosukhin",
  ],
  abstract:
    "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.",
  pdf_url: "https://arxiv.org/pdf/1706.03762.pdf",
  html_url: "https://arxiv.org/abs/1706.03762",
  sections: [
    {
      id: "section-3-1",
      title: "The Transformer Architecture",
      content:
        'Think of the Transformer as a factory with two halves \u2014 an **encoder** that reads and understands the input, and a **decoder** that produces the output one piece at a time.\n\nUnlike older models (RNNs) that process words one-by-one in sequence, the Transformer looks at **all words simultaneously**. It uses a stack of 6 identical layers, each containing two key ingredients: a self-attention mechanism and a feed-forward network. Residual connections and layer normalization keep information flowing smoothly.\n\n**Key takeaway:** The Transformer\u2019s parallel architecture replaces sequential processing, making it dramatically faster to train.',
      level: 1,
      order_index: 0,
      equations: [],
      video_url: "/videos/demo/TransformerEncoderdecoderArchitecture.mp4",
    },
    {
      id: "section-3-2",
      title: "Scaled Dot-Product Attention",
      content:
        'Attention answers a simple question: *"Which parts of the input should I focus on right now?"*\n\nIt works with three ingredients \u2014 **Queries** (what am I looking for?), **Keys** (what\u2019s available?), and **Values** (the actual information). The mechanism computes how well each query matches each key, scales the scores down by $\\sqrt{d_k}$ to prevent them from getting too large, then uses softmax to convert scores into weights. The final output is a weighted blend of the values.\n\n$$\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$\n\n**Key takeaway:** Scaling by $\\sqrt{d_k}$ is what makes this "scaled" dot-product attention \u2014 without it, large dimensions push softmax into regions with vanishing gradients.',
      level: 1,
      order_index: 1,
      equations: [
        "\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V",
      ],
      video_url: "/videos/demo/ScaledDotproductAttention.mp4",
    },
    {
      id: "section-3-3",
      title: "Multi-Head Attention",
      content:
        "A single attention head can only focus on one type of relationship at a time. **Multi-head attention** runs 8 attention heads in parallel, each with different learned projections. One head might track syntax, another might track meaning, and another might track position.\n\nAfter each head computes its own attention output, the results are concatenated and projected through a final linear layer:\n\n$$\\text{MultiHead}(Q, K, V) = \\text{Concat}(\\text{head}_1, \\ldots, \\text{head}_h)W^O$$\n\n**Key takeaway:** Multiple heads let the model attend to different types of relationships simultaneously \u2014 like reading a sentence with 8 different lenses.",
      level: 1,
      order_index: 2,
      equations: [
        "\\text{MultiHead}(Q, K, V) = \\text{Concat}(\\text{head}_1, \\ldots, \\text{head}_h)W^O",
      ],
      video_url: "/videos/demo/MultiheadAttention.mp4",
    },
    {
      id: "section-3-5",
      title: "Positional Encoding",
      content:
        'Since the Transformer processes all words at once (not sequentially), it has no built-in sense of word order. Positional encoding solves this by adding a unique "position signal" to each word embedding.\n\nThe encoding uses sine and cosine waves of different frequencies \u2014 think of it like giving each position its own unique musical chord. Nearby positions sound similar, distant positions sound different:\n\n$$PE_{(pos, 2i)} = \\sin\\left(\\frac{pos}{10000^{2i/d_{\\text{model}}}}\\right)$$\n\n**Key takeaway:** Sinusoidal encodings let the model learn relative positions \u2014 it can figure out "word B is 3 positions after word A" through linear transformations.',
      level: 1,
      order_index: 3,
      equations: [
        "PE_{(pos, 2i)} = \\sin\\left(\\frac{pos}{10000^{2i/d_{\\text{model}}}}\\right)",
      ],
      video_url: "/videos/demo/SinusoidalPositionalEncoding.mp4",
    },
    {
      id: "section-4",
      title: "Why Self-Attention",
      content:
        "Why not just use RNNs or CNNs? The answer comes down to three things: **speed**, **parallelism**, and **long-range connections**.\n\nAn RNN must process words one after another \u2014 to connect the first word to the last in a 100-word sentence, information must travel through 100 steps. Self-attention connects every word to every other word in just **one step** (O(1) path length vs O(n) for RNNs).\n\nSelf-attention is also faster when the sequence length is shorter than the model dimension (which is most real-world cases), and it produces more interpretable models \u2014 you can literally see which words each head is attending to.\n\n**Key takeaway:** Self-attention trades the sequential bottleneck of RNNs for constant-time connections between any two positions.",
      level: 1,
      order_index: 4,
      equations: [],
      video_url:
        "/videos/demo/PathLengthComparisonSelfattentionVsRnnVsCnn.mp4",
    },
  ],
};

export const MOCK_STATUS: ProcessingStatus = {
  job_id: "mock-job-123",
  status: "completed",
  progress: 1.0,
  sections_completed: 5,
  sections_total: 5,
  current_step: "Complete",
};
