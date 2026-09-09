/** Section shape the reader renders (CardStack/StackCard) — built by the
 *  paper page from the API response. */
export type SectionVideoModel = {
  vizId: string;
  videoUrl: string;
  concept: string;
};

export type ScrollySectionModel = {
  id: string;
  title: string;
  content: string;
  level?: 1 | 2 | 3;
  equations?: string[];
  videoUrl?: string;
  vizId?: string;
  videos?: SectionVideoModel[];
};
