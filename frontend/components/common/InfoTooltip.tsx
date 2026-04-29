"use client";
/**
 * Small ⓘ icon with a hover/focus-triggered popover.
 *
 * Used next to KPI labels and other concise headings
 * where the metric needs a longer "what + how"
 * explanation that doesn't fit inline. Native HTML
 * ``title`` attribute is too cramped for multi-line
 * formula text and disappears on slight cursor
 * movement, so we ship a controlled popover instead.
 *
 * Accessibility:
 * - Trigger is a real <button> with aria-label.
 * - Popover content is announced via role="tooltip".
 * - Opens on hover, keyboard focus, AND click — the
 *   click toggle keeps it usable on touch.
 *
 * Positioning:
 * - Default ``"auto"`` measures the trigger's position
 *   on open and picks ``start | center | end`` so the
 *   popover never clips the viewport. Callers can pin
 *   the side via the ``placement`` prop.
 *   - ``start``  = popover anchored to the trigger's
 *                  left edge, flows right (use when
 *                  the trigger is near the LEFT edge
 *                  of the viewport)
 *   - ``center`` = popover horizontally centred over
 *                  the trigger
 *   - ``end``    = popover anchored to the trigger's
 *                  right edge, flows left (use when
 *                  the trigger is near the RIGHT edge
 *                  of the viewport)
 */

import {
  useEffect, useId, useRef, useState,
  type ReactNode,
} from "react";

type Placement = "auto" | "start" | "center" | "end";
type ResolvedPlacement = Exclude<Placement, "auto">;

interface InfoTooltipProps {
  /** Popover body — JSX so callers can format it. */
  children: ReactNode;
  /** Override the default 18rem popover width. */
  widthClass?: string;
  /**
   * ``"auto"`` (default) auto-detects the side that
   * fits in the viewport. Pin to a specific side with
   * ``"start"`` / ``"center"`` / ``"end"``.
   */
  placement?: Placement;
  /** Optional aria-label override. */
  label?: string;
}

// Approximate popover width to drive auto-placement.
// Matches the default ``widthClass="w-72"`` (= 18rem
// = 288px). Callers that override widthClass to
// something dramatically wider should pin placement.
const POPOVER_WIDTH_PX = 288;
// Minimum gap from viewport edge before we flip side.
const EDGE_PADDING_PX = 12;

export function InfoTooltip({
  children,
  widthClass = "w-72",
  placement = "auto",
  label = "Show metric definition",
}: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] =
    useState<ResolvedPlacement>("center");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const id = useId();

  // Auto-placement: when ``placement === "auto"``,
  // measure the trigger on open and pick the side
  // that doesn't clip the viewport. The setState is
  // deferred past the synchronous effect body via
  // Promise.resolve so eslint-plugin-react-hooks v5
  // sees it as an async-callback update rather than a
  // sync setState (matches the Sprint 8 lint pattern).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    void Promise.resolve().then(() => {
      if (!alive) return;
      if (placement !== "auto") {
        setResolved(placement);
        return;
      }
      if (typeof window === "undefined") return;
      const el = triggerRef.current;
      if (!el) return;

      const rect = el.getBoundingClientRect();
      const vw = window.innerWidth;
      const triggerCentre =
        rect.left + rect.width / 2;
      const halfPopover = POPOVER_WIDTH_PX / 2;

      // Centre fits if both halves clear the viewport.
      if (
        triggerCentre - halfPopover
          >= EDGE_PADDING_PX
        && triggerCentre + halfPopover
           <= vw - EDGE_PADDING_PX
      ) {
        setResolved("center");
        return;
      }
      // Trigger is closer to the left edge → anchor
      // the popover to the trigger's left and flow
      // right.
      if (triggerCentre < vw / 2) {
        setResolved("start");
      } else {
        // Closer to right edge → anchor right, flow
        // left.
        setResolved("end");
      }
    });
    return () => {
      alive = false;
    };
  }, [open, placement]);

  const positionClass =
    resolved === "center"
      ? "left-1/2 -translate-x-1/2"
      : resolved === "start"
        ? "left-0"
        : "right-0";

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className={
          "ml-1 inline-flex h-4 w-4 items-center " +
          "justify-center rounded-full border " +
          "border-gray-400 dark:border-gray-500 " +
          "text-[10px] font-semibold text-gray-500 " +
          "dark:text-gray-400 cursor-help " +
          "hover:border-gray-600 hover:text-gray-700 " +
          "dark:hover:border-gray-300 " +
          "dark:hover:text-gray-200 " +
          "focus:outline-none focus:ring-2 " +
          "focus:ring-indigo-400"
        }
      >
        i
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={
            "absolute top-full z-50 mt-1 " +
            "rounded-md border border-gray-200 " +
            "dark:border-gray-700 bg-white " +
            "dark:bg-gray-800 px-3 py-2 text-xs " +
            "leading-relaxed text-gray-700 " +
            "dark:text-gray-200 shadow-lg " +
            "normal-case tracking-normal font-normal " +
            positionClass + " " + widthClass
          }
        >
          {children}
        </span>
      )}
    </span>
  );
}
