"use client";
/**
 * 8th tab on the Advanced Analytics page — in-app reference
 * for every reporting column. Pure frontend (no backend
 * fetch) — content lives in `columnHelp.ts`.
 *
 * UX:
 * - Search filters across column label, description, and
 *   trading takeaway (case-insensitive substring).
 * - Categories render as collapsible sections — first one
 *   open, rest closed by default. "Expand all" / "Collapse
 *   all" affordance for power-skim.
 * - Each column rendered in a 3-column grid: What it is,
 *   How it's calculated, Trading takeaway.
 */

import { useMemo, useState } from "react";

import {
  CATEGORY_BLURBS,
  COLUMN_DOCS,
  GLOSSARY,
  groupByCategory,
  type ColumnCategory,
  type ColumnDoc,
} from "./columnHelp";

export function HelpTab() {
  const [search, setSearch] = useState("");
  const [openCategories, setOpenCategories] = useState<Set<ColumnCategory>>(
    () => new Set(["Identity"]),
  );

  const needle = search.trim().toLowerCase();

  const filtered = useMemo(() => {
    const groups = groupByCategory();
    if (!needle) return groups;
    return groups
      .map((g) => ({
        ...g,
        docs: g.docs.filter((d) => matches(d, needle)),
      }))
      .filter((g) => g.docs.length > 0);
  }, [needle]);

  const matchedCount = useMemo(
    () => filtered.reduce((sum, g) => sum + g.docs.length, 0),
    [filtered],
  );

  const toggleCategory = (cat: ColumnCategory) => {
    setOpenCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  };

  const expandAll = () => {
    setOpenCategories(new Set(filtered.map((g) => g.category)));
  };

  const collapseAll = () => {
    setOpenCategories(new Set());
  };

  // While searching, force-open every group with hits so
  // the user immediately sees results without clicking.
  const effectiveOpen = needle
    ? new Set(filtered.map((g) => g.category))
    : openCategories;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Column Reference
          </h2>
          <p className="mt-1 max-w-3xl text-xs text-gray-500 dark:text-gray-400">
            Every column on the Advanced Analytics tabs — what it
            measures, how it&apos;s calculated, and how to use it in a
            trade decision. Search across all {COLUMN_DOCS.length} fields
            below.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search columns…"
            data-testid="advanced-analytics-help-search"
            aria-label="Search column reference"
            className="w-48 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1 text-xs text-gray-700 dark:text-gray-200 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          {!needle && (
            <>
              <button
                type="button"
                onClick={expandAll}
                className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                Expand all
              </button>
              <button
                type="button"
                onClick={collapseAll}
                className="text-xs text-gray-500 dark:text-gray-400 hover:underline"
              >
                Collapse all
              </button>
            </>
          )}
        </div>
      </div>

      {needle && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {matchedCount} match{matchedCount === 1 ? "" : "es"} for{" "}
          <span className="font-mono text-gray-700 dark:text-gray-300">
            &ldquo;{search}&rdquo;
          </span>
        </p>
      )}

      {/* Glossary block — always visible (small, scannable). */}
      {!needle && (
        <details
          className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-4 py-3"
          open
        >
          <summary className="cursor-pointer select-none text-xs font-semibold text-gray-700 dark:text-gray-200">
            Quick glossary
          </summary>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
            {GLOSSARY.map((g) => (
              <div key={g.term} className="flex gap-2">
                <dt className="shrink-0 font-mono font-semibold text-gray-700 dark:text-gray-200">
                  {g.term}
                </dt>
                <dd className="text-gray-600 dark:text-gray-400">
                  {g.definition}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-8 text-center text-xs text-gray-500">
          No columns match &ldquo;{search}&rdquo;. Try a shorter substring.
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((g) => {
            const isOpen = effectiveOpen.has(g.category);
            return (
              <section
                key={g.category}
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                data-testid={`advanced-analytics-help-category-${g.category.toLowerCase()}`}
              >
                <button
                  type="button"
                  onClick={() => toggleCategory(g.category)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800/50 rounded-t-lg"
                >
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {g.category}
                      <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                        ({g.docs.length} column{g.docs.length === 1 ? "" : "s"})
                      </span>
                    </h3>
                    <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                      {CATEGORY_BLURBS[g.category]}
                    </p>
                  </div>
                  <span
                    className="text-xs text-gray-400 dark:text-gray-500"
                    aria-hidden
                  >
                    {isOpen ? "▾" : "▸"}
                  </span>
                </button>
                {isOpen && (
                  <div className="divide-y divide-gray-100 dark:divide-gray-800 border-t border-gray-200 dark:border-gray-700">
                    {g.docs.map((doc) => (
                      <ColumnHelpRow key={doc.key} doc={doc} highlight={needle} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  doc: ColumnDoc;
  highlight: string;
}

function ColumnHelpRow({ doc, highlight }: RowProps) {
  return (
    <article
      className="grid gap-3 px-4 py-3 sm:grid-cols-12"
      data-testid={`advanced-analytics-help-row-${doc.key}`}
    >
      <header className="sm:col-span-3">
        <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          <Highlight text={doc.label} needle={highlight} />
        </h4>
        <code className="mt-0.5 block text-[11px] font-mono text-gray-500 dark:text-gray-400 break-all">
          {doc.key}
        </code>
      </header>
      <div className="sm:col-span-9 space-y-2">
        <p className="text-xs text-gray-700 dark:text-gray-300">
          <Highlight text={doc.description} needle={highlight} />
        </p>
        <div className="rounded-md bg-gray-50 dark:bg-gray-800/60 px-3 py-2 font-mono text-[11px] text-gray-700 dark:text-gray-200 break-words">
          <span className="mr-2 text-gray-400">∑</span>
          {doc.formula}
        </div>
        <p className="text-xs text-indigo-700 dark:text-indigo-300">
          <span className="mr-1 font-semibold">Trade:</span>
          <Highlight text={doc.tradingTakeaway} needle={highlight} />
        </p>
      </div>
    </article>
  );
}

function Highlight({ text, needle }: { text: string; needle: string }) {
  if (!needle) return <>{text}</>;
  const lower = text.toLowerCase();
  const idx = lower.indexOf(needle);
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded-sm bg-yellow-200 px-0.5 text-gray-900 dark:bg-yellow-900/60 dark:text-gray-100">
        {text.slice(idx, idx + needle.length)}
      </mark>
      {text.slice(idx + needle.length)}
    </>
  );
}

function matches(doc: ColumnDoc, needle: string): boolean {
  return (
    doc.label.toLowerCase().includes(needle) ||
    doc.key.toLowerCase().includes(needle) ||
    doc.description.toLowerCase().includes(needle) ||
    doc.tradingTakeaway.toLowerCase().includes(needle) ||
    doc.formula.toLowerCase().includes(needle) ||
    doc.category.toLowerCase().includes(needle)
  );
}
