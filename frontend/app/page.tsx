"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { PlaceholdersAndVanishInput } from "@/components/ui/placeholders-and-vanish-input";
import { MosaicBackground } from "@/components/ui/mosaic-background";
import { ShardField } from "@/components/ui/glass-shard";
import { GlassCard } from "@/components/ui/glass-card";

function extractArxivId(inputRaw: string): string | null {
  const input = inputRaw.trim();
  if (!input) return null;

  const directNew = input.match(/^\d{4}\.\d{4,5}(v\d+)?$/i);
  if (directNew) return directNew[0];

  const directOld = input.match(/^[a-z-]+(\.[a-z]{2})?\/\d{7}(v\d+)?$/i);
  if (directOld) return directOld[0];

  const urlAbs = input.match(/arxiv\.org\/abs\/([^?\s#]+)/i);
  if (urlAbs?.[1]) return decodeURIComponent(urlAbs[1]).replace(/\/$/, "");

  const urlPdf = input.match(/arxiv\.org\/pdf\/([^?\s#]+?)(?:\.pdf)?$/i);
  if (urlPdf?.[1]) return decodeURIComponent(urlPdf[1]).replace(/\/$/, "");

  return null;
}

const placeholders = [
  "Paste an arXiv URL or ID...",
  "1706.03762 (Attention Is All You Need)",
  "https://arxiv.org/abs/2005.14165",
  "2303.08774 (GPT-4 Technical Report)",
  "1810.04805 (BERT)",
];

export default function Home() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [touched, setTouched] = useState(false);

  const parsedId = useMemo(() => extractArxivId(value), [value]);
  const canSubmit = Boolean(parsedId);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!parsedId) return;
    router.push(`/abs/${encodeURIComponent(parsedId)}`);
  }

  return (
    <main className="min-h-dvh relative overflow-hidden bg-black">
      {/* Mosaic background with arXiv logo */}
      <MosaicBackground showLogo logoYFraction={0.12} />

      {/* Floating glass shards */}
      <ShardField />

      <div className="relative z-10 mx-auto w-full max-w-6xl px-6">
        {/* ── First viewport: Logo (clear) + search bar below ── */}
        <section className="min-h-dvh flex flex-col">
          {/* Spacer — keeps the logo area clear */}
          <div className="flex-1" />

          {/* Search area — pinned to lower portion of viewport */}
          <div className="max-w-4xl mx-auto w-full text-center pb-16 sm:pb-24">
            {/* Subtitle */}
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.5 }}
              className="text-lg sm:text-xl text-white/40 max-w-2xl mx-auto leading-relaxed font-light"
            >
              Paste any arXiv paper. Watch as it turns complex papers
              into digestible and <span className="text-white/60 font-medium">visually</span> appealing video explanations.
            </motion.p>

            {/* Input Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.8 }}
              className="mt-10 max-w-xl mx-auto"
            >
              <div className="relative">
                {/* Decorative brackets */}
                <div className="absolute -left-4 top-1/2 -translate-y-1/2 text-3xl text-white/10 font-light select-none hidden sm:block">
                  [
                </div>
                <div className="absolute -right-4 top-1/2 -translate-y-1/2 text-3xl text-white/10 font-light select-none hidden sm:block">
                  ]
                </div>

                <PlaceholdersAndVanishInput
                  placeholders={placeholders}
                  value={value}
                  onChange={(e) => {
                    setValue(e.target.value);
                    setTouched(true);
                  }}
                  onSubmit={onSubmit}
                  disabled={!canSubmit && touched && value.length > 0}
                />
              </div>

              {/* Status feedback */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1.0 }}
                className="mt-4 h-6 text-sm"
              >
                {parsedId ? (
                  <span className="text-[#7dd19b] flex items-center justify-center gap-2">
                    <span className="text-lg">✓</span>
                    <span>Detected:{" "}</span>
                    <span className="font-mono bg-[#7dd19b]/10 px-2 py-0.5 rounded">{parsedId}</span>
                  </span>
                ) : touched && value ? (
                  <span className="text-[#f27066]">
                    Enter a valid arXiv URL or paper ID
                  </span>
                ) : null}
              </motion.div>
            </motion.div>

            {/* Quick Examples */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6, delay: 1.2 }}
              className="mt-8 flex flex-wrap items-center justify-center gap-3"
            >
              <span className="text-sm text-white/30">Try these:</span>
              {[
                { id: "1706.03762", label: "Transformers", icon: "◇" },
                { id: "2005.14165", label: "GPT-3", icon: "◈" },
                { id: "2303.08774", label: "GPT-4", icon: "◆" },
              ].map((example) => (
                <motion.button
                  key={example.id}
                  whileHover={{ scale: 1.05, y: -2 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => setValue(example.id)}
                  className="group rounded-xl bg-white/[0.04] px-4 py-2.5 text-sm border border-white/[0.08] transition-all hover:bg-white/[0.07] hover:border-white/[0.14]"
                >
                  <span className="text-white/40 mr-2">{example.icon}</span>
                  <span className="text-white/60 font-mono">{example.id}</span>
                  <span className="text-white/30 ml-2">({example.label})</span>
                </motion.button>
              ))}
            </motion.div>
          </div>
        </section>

        {/* Pro Tip Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 2.2 }}
          className="mt-20 max-w-2xl mx-auto"
        >
          <GlassCard spotlight className="p-8">
            <div className="flex items-center gap-4 mb-4">
              <div className="h-12 w-12 rounded-xl bg-white/[0.06] flex items-center justify-center border border-white/[0.10]">
                <div
                  className="h-4 w-4 bg-gradient-to-br from-white/50 to-white/20"
                  style={{ clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }}
                />
              </div>
              <div>
                <h3 className="font-semibold text-white/90">Pro Tip</h3>
                <p className="text-sm text-white/40">One edit turns arXiv into ArXivisual</p>
              </div>
            </div>
            <div className="space-y-3 text-sm text-white/45 leading-relaxed">
              <p>
                If your link starts with{" "}
                <code className="text-white/60 bg-white/[0.06] px-1.5 py-0.5 rounded text-xs font-mono">
                  arxiv.org
                </code>
                , just add{" "}
                <code className="text-white/60 bg-white/[0.06] px-1.5 py-0.5 rounded text-xs font-mono">
                  isual
                </code>
                {" "}after{" "}
                <code className="text-white/60 bg-white/[0.06] px-1.5 py-0.5 rounded text-xs font-mono">
                  arxiv
                </code>
                .
              </p>
              <div className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                <p className="font-mono text-xs text-white/50">
                  Before: arxiv.org/abs/1706.03762
                </p>
                <p className="font-mono text-xs text-white/70 mt-1">
                  After:&nbsp;&nbsp;arxivisual.org/abs/1706.03762
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Footer */}
        <motion.footer
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 2.4 }}
          className="mt-20 flex flex-col items-center justify-between gap-4 border-t border-white/[0.06] pt-8 text-sm sm:flex-row"
        >
          <div className="flex items-center gap-3 text-white/30">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
              className="h-3 w-3 bg-gradient-to-br from-white/30 to-white/10"
              style={{ clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }}
            />
            <span>Visualizing mathematics, one paper at a time</span>
          </div>
          <div className="flex items-center gap-4">
            <a
              className="rounded-lg px-3 py-1.5 text-white/40 border border-white/[0.06] transition hover:bg-white/[0.04] hover:text-white/60 hover:border-white/[0.12]"
              href="https://arxiv.org"
              target="_blank"
              rel="noreferrer"
            >
              arXiv
            </a>
            <a
              className="rounded-lg px-3 py-1.5 text-white/40 border border-white/[0.06] transition hover:bg-white/[0.04] hover:text-white/60 hover:border-white/[0.12]"
              href="https://www.manim.community/"
              target="_blank"
              rel="noreferrer"
            >
              Manim
            </a>
            <a
              className="rounded-lg px-3 py-1.5 text-white/40 border border-white/[0.06] transition hover:bg-white/[0.04] hover:text-white/60 hover:border-white/[0.12]"
              href="https://www.3blue1brown.com/"
              target="_blank"
              rel="noreferrer"
            >
              3Blue1Brown
            </a>
          </div>
        </motion.footer>
      </div>
    </main>
  );
}
