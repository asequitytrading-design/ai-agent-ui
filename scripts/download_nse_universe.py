"""Download NSE stock universe across multiple indices.

Fetches live index data for Nifty 50, Nifty 100, Nifty 500,
Nifty Midcap 150, Nifty Smallcap 250, and Nifty Microcap 250
via jugaad-data, merges into a single CSV with pipe-delimited
tags suitable for the pipeline seed command.

Usage::

    source ~/.ai-agent-ui/venv/bin/activate
    python scripts/download_nse_universe.py

    # Then seed:
    PYTHONPATH=.:backend python -m backend.pipeline.runner seed \\
        --csv data/universe/nse_universe.csv

Output: data/universe/nse_universe.csv
"""

import csv
import logging
import os
import time

_logger = logging.getLogger(__name__)

# Index name → tag mapping
_INDICES: list[tuple[str, str]] = [
    ("NIFTY 50", "nifty50"),
    ("NIFTY 100", "nifty100"),
    ("NIFTY 500", "nifty500"),
    ("NIFTY MIDCAP 150", "niftymidcap150"),
    ("NIFTY SMALLCAP 250", "niftysmallcap250"),
    ("NIFTY MICROCAP 250", "niftymicrocap250"),
]


def _fetch_index(
    nse,
    index_name: str,
) -> tuple[set[str], list[dict]]:
    """Fetch constituent symbols and raw data for an index.

    Returns (symbols, data_entries).
    """
    _logger.info("Fetching %s...", index_name)
    data = nse.live_index(index_name)
    symbols: set[str] = set()
    entries: list[dict] = []
    for entry in data.get("data", []):
        sym = entry.get("symbol", "")
        # Skip the index summary row
        if sym and sym != index_name.replace(" ", ""):
            symbols.add(sym)
            entries.append(entry)
    _logger.info(
        "%s: %d constituents",
        index_name,
        len(symbols),
    )
    return symbols, entries


def _classify_cap(
    symbol: str,
    index_sets: dict[str, set[str]],
) -> str:
    """Classify market cap tier based on index membership."""
    if symbol in index_sets.get("nifty100", set()):
        return "largecap"
    # Midcap: in nifty500 but not nifty100, or in midcap150
    nifty500 = index_sets.get("nifty500", set())
    nifty100 = index_sets.get("nifty100", set())
    midcap150 = index_sets.get("niftymidcap150", set())
    if (symbol in nifty500 and symbol not in nifty100) or symbol in midcap150:
        return "midcap"
    return "smallcap"


def main() -> None:
    """Download and generate nse_universe.csv."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    from jugaad_data.nse import NSELive

    nse = NSELive()

    # Fetch all indices -----------------------------------------
    index_sets: dict[str, set[str]] = {}
    all_entries: dict[str, dict] = {}  # symbol → best entry

    for i, (index_name, tag) in enumerate(_INDICES):
        if i > 0:
            time.sleep(1)  # rate limit
        try:
            symbols, entries = _fetch_index(nse, index_name)
            index_sets[tag] = symbols
            # Store entry data (first seen wins for meta)
            for entry in entries:
                sym = entry.get("symbol", "")
                if sym and sym not in all_entries:
                    all_entries[sym] = entry
        except Exception:
            _logger.warning(
                "Failed to fetch %s — skipping",
                index_name,
                exc_info=True,
            )
            index_sets[tag] = set()

    # Build rows ------------------------------------------------
    rows = []
    skipped = 0
    all_symbols = set()
    for syms in index_sets.values():
        all_symbols.update(syms)

    for symbol in all_symbols:
        entry = all_entries.get(symbol)
        if not entry:
            skipped += 1
            continue

        meta = entry.get("meta", {})
        name = meta.get("companyName", "")
        isin = meta.get("isin", "")
        industry = meta.get("industry", "")

        # Skip entries without required fields
        if not name or not isin:
            skipped += 1
            continue

        # Skip non-EQ series
        series_list = meta.get("activeSeries", [])
        if "EQ" not in series_list:
            skipped += 1
            continue

        # Build tags — index membership
        tags = []
        for _index_name, tag in _INDICES:
            if symbol in index_sets.get(tag, set()):
                tags.append(tag)

        # Cap tier tag
        cap = _classify_cap(symbol, index_sets)
        tags.append(cap)

        # Sector filled by yfinance later
        sector = ""

        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "isin": isin,
                "exchange": "NSE",
                "series": "EQ",
                "sector": sector,
                "industry": industry,
                "tags": "|".join(tags),
            }
        )

    _logger.info(
        "Parsed %d stocks (%d skipped)",
        len(rows),
        skipped,
    )

    # Sort by symbol for deterministic output -------------------
    rows.sort(key=lambda r: r["symbol"])

    # Write CSV -------------------------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    out_dir = os.path.join(project_root, "data", "universe")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "nse_universe.csv")

    fieldnames = [
        "symbol",
        "name",
        "isin",
        "exchange",
        "series",
        "sector",
        "industry",
        "tags",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    _logger.info(
        "Written %d rows to %s",
        len(rows),
        out_path,
    )

    # Summary ---------------------------------------------------
    tag_counts: dict[str, int] = {}
    for r in rows:
        for t in r["tags"].split("|"):
            tag_counts[t] = tag_counts.get(t, 0) + 1

    _logger.info("Total stocks: %d", len(rows))
    for tag, count in sorted(tag_counts.items()):
        _logger.info("  %-20s %d", tag, count)

    _logger.info(
        "Next: PYTHONPATH=.:backend python -m "
        "backend.pipeline.runner seed --csv %s",
        out_path,
    )


if __name__ == "__main__":
    main()
