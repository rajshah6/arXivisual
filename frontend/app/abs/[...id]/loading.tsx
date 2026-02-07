export default function Loading() {
  return (
    <main className="min-h-dvh bg-black">
      <div className="mx-auto w-full max-w-6xl px-6 py-10 sm:py-14">
        <div className="h-10 w-28 rounded-lg bg-white/[0.04] border border-white/[0.06]" />

        <div className="mt-8 space-y-3">
          <div className="h-4 w-20 rounded bg-white/[0.04] border border-white/[0.06]" />
          <div className="h-8 w-80 max-w-full rounded bg-white/[0.04] border border-white/[0.06]" />
          <div className="h-4 w-[520px] max-w-full rounded bg-white/[0.04] border border-white/[0.06]" />
          <div className="h-4 w-[440px] max-w-full rounded bg-white/[0.04] border border-white/[0.06]" />
        </div>

        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          <div className="h-28 rounded-2xl bg-white/[0.04] border border-white/[0.06]" />
          <div className="h-28 rounded-2xl bg-white/[0.04] border border-white/[0.06]" />
          <div className="h-28 rounded-2xl bg-white/[0.04] border border-white/[0.06]" />
        </div>

        <div className="mt-8 h-40 rounded-2xl bg-white/[0.04] border border-white/[0.06]" />
      </div>
    </main>
  );
}
