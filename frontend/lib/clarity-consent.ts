/**
 * Microsoft Clarity cookie consent — the one place that talks to Clarity's
 * consent API and remembers the visitor's answer.
 *
 * Clarity's Consent Mode starts EEA/UK/CH visitors (and everyone, once the
 * project has Consent Mode switched on) in "denied": the tag runs cookieless
 * until it is told otherwise. components/ConsentBar.tsx is the notice; on
 * Accept we grant analytics storage only — ads storage stays denied — and on
 * every later page load we replay the stored answer once, before Clarity
 * would set anything (per the Clarity consent docs).
 *
 * Client only. No-op when NEXT_PUBLIC_CLARITY_PROJECT_ID is unset.
 */
import Clarity from "@microsoft/clarity";

declare global {
  interface Window {
    /** Queue stub installed by Clarity.init(); real tag replaces it on load. */
    clarity?: (...args: unknown[]) => void;
  }
}

export const CLARITY_PROJECT_ID = process.env.NEXT_PUBLIC_CLARITY_PROJECT_ID ?? "";

/** Single source of truth for "is Clarity on in this build". */
export function isClarityConfigured(): boolean {
  return Boolean(CLARITY_PROJECT_ID);
}

export type ConsentChoice = "granted" | "denied";

const STORAGE_KEY = "arxivisual.clarity-consent";

export function getStoredConsent(): ConsentChoice | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "granted" || value === "denied" ? value : null;
  } catch {
    return null;
  }
}

function signalConsent(choice: ConsentChoice): void {
  // Clarity.init() installs the window.clarity queue, so a call made before
  // the tag finishes loading is replayed, not lost. Without init (no project
  // id) there is nothing to talk to.
  if (typeof window === "undefined" || typeof window.clarity !== "function") return;
  try {
    Clarity.consentV2({ ad_Storage: "denied", analytics_Storage: choice });
  } catch {
    // Consent signalling must never break the page.
  }
}

/** Persist the visitor's choice and tell Clarity. */
export function setClarityConsent(choice: ConsentChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Private mode / blocked storage: the bar simply asks again next visit.
  }
  signalConsent(choice);
}

/**
 * Once per page load, right after Clarity.init(): replay a stored choice, or
 * — for a first-time visitor — signal "denied" so Clarity stays cookieless
 * everywhere until Accept. Clarity's own default is "denied" only for
 * EEA/UK/CH visitors (Consent Mode); this makes the bar's promise ("it sets
 * cookies only if you accept") true for everyone, whatever the project
 * setting says.
 */
export function applyStoredClarityConsent(): void {
  signalConsent(getStoredConsent() ?? "denied");
}
