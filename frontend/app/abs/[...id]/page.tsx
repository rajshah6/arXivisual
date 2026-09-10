import type { Metadata } from "next";
import { normalizeArxivId } from "@/lib/arxiv-id";
import { paperMetadata } from "@/lib/paper-metadata";
import { PaperPage } from "./PaperPage";

type Params = Promise<{ id?: string[] }>;

/**
 * Server half of the paper route. `generateMetadata` must live in a server
 * module, so the reader itself is the client component in PaperPage.tsx and
 * this file only resolves per-paper metadata and hands the params through.
 */
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { id } = await params;
  return paperMetadata(normalizeArxivId(id));
}

export default function Page({ params }: { params: Params }) {
  return <PaperPage params={params} />;
}
