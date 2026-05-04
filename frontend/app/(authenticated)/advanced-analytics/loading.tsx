/**
 * Static loading shell for the Advanced Analytics
 * route — text-bearing so Lighthouse FCP fires
 * (§6.6 lighthouse-fcp-text-heuristic).
 *
 * The `min-h-[600px]` mirrors the inner content
 * reserve in AdvancedAnalyticsClient (matches the
 * admin-tab convention) so swap into the loaded
 * tree doesn't trip CLS (§5.15 ≤ 0.02 budget).
 */

export default function Loading() {
  return (
    <div className="space-y-6 p-4 sm:p-6">
      <h1 className="text-2xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
        Advanced Analytics
      </h1>
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Loading reports…
      </p>
      <div
        className="min-h-[600px] rounded-lg border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900"
        aria-busy="true"
      />
    </div>
  );
}
