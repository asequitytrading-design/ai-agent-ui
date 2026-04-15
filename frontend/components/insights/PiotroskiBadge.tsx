"use client";
/**
 * Piotroski F-Score badge — color-coded pill.
 *
 * 8-9: green (Strong)
 * 5-7: amber (Moderate)
 * 0-4: red (Weak)
 */

interface PiotroskiBadgeProps {
  score: number;
  label: string;
}

export function PiotroskiBadge({
  score,
  label,
}: PiotroskiBadgeProps) {
  let cls =
    "inline-flex items-center gap-1 " +
    "px-2 py-0.5 rounded-full text-xs " +
    "font-semibold ";
  if (score >= 8) {
    cls +=
      "bg-emerald-100 text-emerald-700 " +
      "dark:bg-emerald-900/30 " +
      "dark:text-emerald-400";
  } else if (score >= 5) {
    cls +=
      "bg-amber-100 text-amber-700 " +
      "dark:bg-amber-900/30 " +
      "dark:text-amber-400";
  } else {
    cls +=
      "bg-red-100 text-red-700 " +
      "dark:bg-red-900/30 dark:text-red-400";
  }
  return (
    <span className={cls} title={label}>
      {score}
    </span>
  );
}
