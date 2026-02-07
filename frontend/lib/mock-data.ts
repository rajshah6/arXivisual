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

// ── GPT-3 Demo Paper ─────────────────────────────────────────────────

export const GPT3_PAPER_ID = "2005.14165";
export const GPT4_PAPER_ID = "2303.08774";

/** All demo paper IDs that have hardcoded data */
export const DEMO_PAPER_IDS = new Set([DEMO_PAPER_ID, GPT3_PAPER_ID, GPT4_PAPER_ID]);

/** Returns the hardcoded Paper for a demo ID, or null if not a demo paper. */
export function getDemoPaper(arxivId: string): Paper | null {
  if (arxivId === DEMO_PAPER_ID) return { ...MOCK_PAPER };
  if (arxivId === GPT3_PAPER_ID) return { ...GPT3_MOCK_PAPER };
  if (arxivId === GPT4_PAPER_ID) return { ...GPT4_MOCK_PAPER };
  return null;
}

export const GPT3_MOCK_PAPER: Paper = {
  paper_id: GPT3_PAPER_ID,
  title: "Language Models are Few-Shot Learners",
  authors: [
    "Tom B. Brown",
    "Benjamin Mann",
    "Nick Ryder",
    "Melanie Subbiah",
    "Jared Kaplan",
    "Prafulla Dhariwal",
    "Arvind Neelakantan",
    "Pranav Shyam",
    "Girish Sastry",
    "Amanda Askell",
    "Sandhini Agarwal",
    "Ariel Herbert-Voss",
    "Gretchen Krueger",
    "Tom Henighan",
    "Rewon Child",
    "Aditya Ramesh",
    "Daniel M. Ziegler",
    "Jeffrey Wu",
    "Clemens Winter",
    "Christopher Hesse",
    "Mark Chen",
    "Eric Sigler",
    "Mateusz Litwin",
    "Scott Gray",
    "Benjamin Chess",
    "Jack Clark",
    "Christopher Berner",
    "Sam McCandlish",
    "Alec Radford",
    "Ilya Sutskever",
    "Dario Amodei",
  ],
  abstract:
    "Recent work has demonstrated substantial gains on many NLP tasks and benchmarks by pre-training on a large corpus of text followed by fine-tuning on a specific task. While typically task-agnostic in architecture, this method still requires task-specific fine-tuning datasets of thousands or tens of thousands of examples. By contrast, humans can generally perform a new language task from only a few examples or from simple instructions \u2014 something which current NLP systems still largely struggle to do. Here we show that scaling up language models greatly improves task-agnostic, few-shot performance, sometimes even reaching competitiveness with prior state-of-the-art fine-tuning approaches.",
  pdf_url: "https://arxiv.org/pdf/2005.14165.pdf",
  html_url: "https://arxiv.org/abs/2005.14165",
  sections: [
    {
      id: "gpt3-section-1",
      title: "In-Context Learning vs Fine-Tuning",
      content:
        'GPT-3 introduced a radical idea: instead of **fine-tuning** a model on thousands of labeled examples, you can teach it new tasks simply by showing examples *inside the prompt*. This is called **in-context learning**.\n\nTraditional fine-tuning updates a model\u2019s weights for each new task, requiring expensive retraining and large datasets. In-context learning skips this entirely \u2014 the model reads a few demonstrations at inference time and generalizes on the spot, with zero parameter updates.\n\n**Key takeaway:** In-context learning replaces the "train a new model per task" paradigm with "describe the task in the prompt" \u2014 making GPT-3 a general-purpose few-shot learner.',
      level: 1,
      order_index: 0,
      equations: [],
      video_url: "/videos/demo/in_context_learning_vs_fine_tuning.mp4",
    },
    {
      id: "gpt3-section-2",
      title: "The Few-Shot Learning Mechanism",
      content:
        'Few-shot learning in GPT-3 works by structuring the prompt as a sequence of **demonstration pairs** followed by a new query. For example: *"Translate English to French: sea otter \u2192 loutre de mer, cheese \u2192 fromage, hello \u2192"*. The model completes the pattern.\n\nThis mechanism has inherent **uncertainty** \u2014 with only a handful of examples, the model may latch onto spurious patterns or fail on edge cases. Performance varies significantly depending on prompt formatting, example selection, and task complexity.\n\n**Key takeaway:** Few-shot prompting leverages the model\u2019s pattern-completion ability, but its reliability depends heavily on how examples are chosen and structured.',
      level: 1,
      order_index: 1,
      equations: [],
      video_url: "/videos/demo/few_shot_learning_mechanism_uncertainty.mp4",
    },
    {
      id: "gpt3-section-3",
      title: "In-Context Learning at Scale",
      content:
        'One of GPT-3\u2019s most striking findings is that **in-context learning ability emerges with scale**. Small language models barely benefit from in-context examples, but as models grow larger, their ability to learn from prompt examples improves dramatically.\n\nThe authors tested models ranging from 125M to 175B parameters. On tasks like arithmetic, unscrambling words, and reading comprehension, the gap between zero-shot and few-shot performance **widens** as model size increases \u2014 meaning larger models extract more signal from the same examples.\n\n**Key takeaway:** In-context learning is not just a trick \u2014 it is an **emergent capability** that becomes increasingly powerful with model scale.',
      level: 1,
      order_index: 2,
      equations: [],
      video_url: "/videos/demo/in_context_learning_scaling.mp4",
    },
    {
      id: "gpt3-section-4",
      title: "Few-Shot Performance Scaling",
      content:
        'GPT-3 demonstrated a remarkably consistent **scaling law** for few-shot performance: across dozens of benchmarks, larger models achieve better results with the same number of in-context examples. The relationship follows an approximate power law:\n\n$$L(N) \\propto N^{-\\alpha}$$\n\nwhere $L$ is the loss, $N$ is the number of parameters, and $\\alpha$ is a task-dependent scaling exponent. On some tasks like translation and question answering, the 175B model with just a few examples matched or exceeded fine-tuned models trained on thousands of labeled samples.\n\n**Key takeaway:** The scaling law $L(N) \\propto N^{-\\alpha}$ means predictable improvement \u2014 doubling parameters yields a consistent reduction in few-shot error across tasks.',
      level: 1,
      order_index: 3,
      equations: ["L(N) \\propto N^{-\\alpha}"],
      video_url: "/videos/demo/few_shot_performance_scaling.mp4",
    },
    {
      id: "gpt3-section-5",
      title: "Training Data Mixture and Weighted Sampling",
      content:
        "GPT-3 was trained on a carefully curated mixture of datasets, not just raw internet text. The training corpus blended **Common Crawl** (filtered and deduplicated), **WebText2**, **Books1**, **Books2**, and **Wikipedia** \u2014 totaling roughly 570 GB of filtered text.\n\nCritically, datasets were **not sampled proportionally** to their size. Higher-quality sources like Wikipedia and books were upsampled (seen more than once per epoch), while the massive Common Crawl was downsampled to reduce noise. This weighted sampling strategy proved essential for model quality.\n\n**Key takeaway:** Data quality trumps quantity \u2014 GPT-3\u2019s weighted sampling ensured the model trained more on cleaner, higher-quality sources despite their smaller size.",
      level: 1,
      order_index: 4,
      equations: [],
      video_url:
        "/videos/demo/training_data_mixture_and_weighted_sampling.mp4",
    },
  ],
};

// ── GPT-4 Demo Paper ─────────────────────────────────────────────────

export const GPT4_MOCK_PAPER: Paper = {
  paper_id: GPT4_PAPER_ID,
  title: "GPT-4 Technical Report",
  authors: [
    "OpenAI",
    "Josh Achiam",
    "Steven Adler",
    "Sandhini Agarwal",
    "Lama Ahmad",
    "Ilge Akkaya",
    "Florencia Leoni Aleman",
    "Diogo Almeida",
    "Janko Altenschmidt",
    "Sam Altman",
    "Shyamal Anadkat",
    "Red Avila",
    "Igor Babuschkin",
    "Suchir Balaji",
  ],
  abstract:
    "We report the development of GPT-4, a large-scale, multimodal model which can accept image and text inputs and produce text outputs. While less capable than humans in many real-world scenarios, GPT-4 exhibits human-level performance on various professional and academic benchmarks, including passing a simulated bar exam with a score around the top 10% of test takers. GPT-4 is a Transformer-based model pre-trained to predict the next token in a document, using both publicly available data and data licensed from third-party providers.",
  pdf_url: "https://arxiv.org/pdf/2303.08774.pdf",
  html_url: "https://arxiv.org/abs/2303.08774",
  sections: [
    {
      id: "gpt4-section-1",
      title: "Unidirectional vs Bidirectional Context",
      content:
        'GPT-4, like its predecessors, uses a **unidirectional** (left-to-right) architecture \u2014 it reads text from beginning to end and predicts the next token based only on what came before. This contrasts with **bidirectional** models like BERT, which look at surrounding context in both directions.\n\nWhy does this matter? Unidirectional processing makes GPT-4 a natural *generator* \u2014 it can produce coherent text, code, and reasoning step by step. Bidirectional models are better at *understanding* existing text but struggle with open-ended generation.\n\n**Key takeaway:** GPT-4\u2019s left-to-right design is what makes it a powerful text generator \u2014 each token is produced by attending only to prior context, enabling fluent autoregressive output.',
      level: 1,
      order_index: 0,
      equations: [],
      video_url: "/videos/demo/unidirectional_vs_bidirectional_context.mp4",
    },
    {
      id: "gpt4-section-2",
      title: "In-Context Learning vs Fine-Tuning",
      content:
        'GPT-4 pushes **in-context learning** further than GPT-3 by accepting both text and image inputs, opening up entirely new task categories without any fine-tuning. You can show it a photo of a diagram and ask questions about it \u2014 all within a single prompt.\n\nWith context windows up to 32k tokens, GPT-4 can absorb far more demonstration examples and reference material than its predecessors. This longer context means richer in-context learning \u2014 effectively giving the model a larger "working memory" for each task.\n\n**Key takeaway:** GPT-4\u2019s multimodal inputs and extended context window make in-context learning more versatile and powerful, reducing the need for fine-tuning even further.',
      level: 1,
      order_index: 1,
      equations: [],
      video_url: "/videos/demo/gpt4_in_context_learning_vs_fine_tuning.mp4",
    },
    {
      id: "gpt4-section-3",
      title: "Few-Shot vs Fine-Tuning Performance",
      content:
        "GPT-4\u2019s few-shot capabilities crossed a remarkable threshold: on many professional benchmarks, it **matched or exceeded fine-tuned specialist models** without any task-specific training. It scored in the top 10% on the simulated bar exam and achieved high marks on the SAT, GRE, and AP exams.\n\nThis was a turning point \u2014 previous models could do well on narrow NLP benchmarks, but GPT-4 demonstrated broad competence across domains from law to biology to mathematics, all using the same frozen model weights with only prompt-based guidance.\n\n**Key takeaway:** GPT-4 demonstrated that a single general-purpose model with few-shot prompting can rival fine-tuned specialists across a wide range of professional and academic tasks.",
      level: 1,
      order_index: 2,
      equations: [],
      video_url:
        "/videos/demo/in_context_learning_few_shot_vs_fine_tuning.mp4",
    },
    {
      id: "gpt4-section-4",
      title: "Scaling Laws for Few-Shot Learning",
      content:
        'A breakthrough in the GPT-4 project was **predictable scaling**: the team accurately forecast GPT-4\u2019s final performance using only small-scale training runs. By fitting a scaling law to models 1,000\u201310,000x smaller, they could predict the loss on the full model:\n\n$$L(C) = aC^{-\\alpha} + b$$\n\nwhere $L$ is the loss, $C$ is the compute budget, and $a$, $\\alpha$, $b$ are fitted constants. This meant the team could estimate GPT-4\u2019s capabilities *before* spending millions on training.\n\n**Key takeaway:** Predictable scaling laws $L(C) = aC^{-\\alpha} + b$ let researchers forecast model performance from small experiments \u2014 transforming AI development from guesswork into engineering.',
      level: 1,
      order_index: 3,
      equations: ["L(C) = aC^{-\\alpha} + b"],
      video_url: "/videos/demo/scaling_laws_for_few_shot_learning.mp4",
    },
  ],
};
