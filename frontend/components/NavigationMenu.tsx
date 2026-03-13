/**
 * Responsive navigation: mobile slide-out drawer + desktop floating grid button.
 *
 * On viewports below ``md`` (768 px) the hamburger button in
 * :component:`ChatHeader` toggles a full-height slide-out drawer from the
 * left.  On ``md+`` the original bottom-right floating grid button is shown.
 *
 * Only items the current user is authorised to see are rendered.  The ``admin``
 * nav item is visible when the user is a superuser OR has the ``admin`` page
 * permission granted by a superuser.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { NAV_ITEMS, type View } from "@/lib/constants";
import type { UserProfile } from "@/hooks/useEditProfile";

interface NavigationMenuProps {
  menuOpen: boolean;
  setMenuOpen: (v: boolean | ((prev: boolean) => boolean)) => void;
  menuRef: RefObject<HTMLDivElement | null>;
  currentView: View;
  onSwitchView: (v: View) => void;
  profile: UserProfile | null;
}

function canSeeItem(
  item: typeof NAV_ITEMS[number],
  profile: UserProfile | null,
): boolean {
  if (item.superuserOnly) {
    if (!profile) return false;
    if (profile.role === "superuser") return true;
    return profile.page_permissions?.admin === true;
  }
  if (item.requiresInsights) {
    if (!profile) return false;
    if (profile.role === "superuser") return true;
    return profile.page_permissions?.insights === true;
  }
  return true;
}

export function NavigationMenu({
  menuOpen,
  setMenuOpen,
  menuRef,
  currentView,
  onSwitchView,
  profile,
}: NavigationMenuProps) {
  const visibleItems = useMemo(
    () => NAV_ITEMS.filter((item) => canSeeItem(item, profile)),
    [profile],
  );

  // Lock body scroll when mobile drawer is open.
  useEffect(() => {
    if (menuOpen) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [menuOpen]);

  const navList = (mobile: boolean) =>
    visibleItems.map((item, idx) => (
      <div key={item.view}>
        {idx > 0 && <div className="border-t border-gray-100" />}
        <button
          onClick={() => onSwitchView(item.view)}
          data-testid={`nav-item-${item.view}`}
          className={`w-full flex items-center gap-3 text-sm transition-colors text-left ${
            mobile ? "px-5 py-4" : "px-4 py-3"
          } ${
            currentView === item.view
              ? "bg-indigo-50 text-indigo-600 font-medium"
              : "text-gray-700 hover:bg-gray-50 hover:text-indigo-600"
          }`}
        >
          {item.icon}
          {item.label}
          {currentView === item.view && (
            <span className="ml-auto w-1.5 h-1.5 rounded-full bg-indigo-500" />
          )}
        </button>
      </div>
    ));

  return (
    <>
      {/* ── Mobile drawer (< md) ──────────────────────────────── */}
      {menuOpen && (
        <div className="fixed inset-0 z-50 md:hidden" data-testid="mobile-nav-drawer">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 transition-opacity"
            onClick={() => setMenuOpen(false)}
          />
          {/* Drawer panel */}
          <nav className="absolute inset-y-0 left-0 w-64 bg-white shadow-xl flex flex-col animate-slide-in-left">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <span className="text-sm font-semibold text-gray-900">
                Navigation
              </span>
              <button
                onClick={() => setMenuOpen(false)}
                className="w-11 h-11 flex items-center justify-center text-gray-400 hover:text-gray-600 rounded-lg"
                aria-label="Close menu"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">{navList(true)}</div>
          </nav>
        </div>
      )}

      {/* ── Desktop floating grid button (md+) ────────────────── */}
      <div
        className="fixed bottom-6 right-6 z-50 hidden md:block"
        ref={menuRef}
      >
        <button
          onClick={() => setMenuOpen((v) => !v)}
          title="Open navigation"
          data-testid="nav-menu-toggle"
          className="w-11 h-11 rounded-xl bg-white border border-gray-200 shadow-md flex items-center justify-center text-gray-500 hover:text-indigo-600 hover:border-indigo-300 hover:shadow-lg transition-all"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" />
            <rect x="14" y="3" width="7" height="7" />
            <rect x="3" y="14" width="7" height="7" />
            <rect x="14" y="14" width="7" height="7" />
          </svg>
        </button>

        {menuOpen && (
          <div className="absolute bottom-14 right-0 bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden min-w-[160px]">
            {navList(false)}
          </div>
        )}
      </div>
    </>
  );
}
