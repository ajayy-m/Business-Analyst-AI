import { useState } from 'react';

/**
 * The product's core principle -- every number is computed by code, the
 * LLM only narrates it -- made visible and interactive. Click a chip to
 * see exactly what produced the number next to it.
 */
export default function EvidenceChip({ label, detail }) {
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className="figure ml-1 rounded-sm border border-ledger-blue/40 bg-ledger-blue/5 px-1.5 py-0.5 text-[11px] text-ledger-blue hover:bg-ledger-blue/10 transition-colors"
      >
        {label}
      </button>
      {open && (
        <div className="figure absolute z-20 top-full mt-1 left-0 w-max max-w-xs rounded-sm border border-line bg-paper p-2 text-[11px] text-ink shadow-lg whitespace-pre-wrap">
          {detail}
        </div>
      )}
    </span>
  );
}
