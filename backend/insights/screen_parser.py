"""ScreenQL — query parser and SQL generator.

Parses a human-readable stock screener query into an
AST, validates against a field catalog, and generates
parameterized DuckDB SQL.

Syntax
------
  field operator value [AND|OR field operator value]
  (field operator value OR field operator value) AND ...

Operators: >, <, >=, <=, =, !=, CONTAINS
Connectors: AND, OR (explicit), newlines (implicit AND)
Values: numbers (15, 0.5), strings ("Technology")
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

_logger = logging.getLogger(__name__)

MAX_CONDITIONS = 20

# ---------------------------------------------------------------
# Field catalog
# ---------------------------------------------------------------


class FieldType(Enum):
    NUMBER = auto()
    TEXT = auto()
    ARRAY = auto()


@dataclass(frozen=True, slots=True)
class FieldDef:
    table: str
    column: str
    type: FieldType
    label: str
    category: str


# Table aliases used in CTE assembly:
#   ci  = company_info (latest per ticker)
#   as_ = analysis_summary (latest per ticker)
#   ps  = piotroski_scores (latest per ticker)
#   fr  = forecast_runs (latest per ticker)
#   ss  = sentiment_scores (latest per ticker)
#   qr  = quarterly_results (latest quarter)
#   sr  = stock_registry (PG, joined via subquery)
#   st  = stock_tags (PG, joined via subquery)

FIELD_CATALOG: dict[str, FieldDef] = {
    # --- Identity (7) ---
    "ticker": FieldDef(
        "ci", "ticker", FieldType.TEXT,
        "Ticker", "Identity",
    ),
    "company_name": FieldDef(
        "ci", "company_name", FieldType.TEXT,
        "Company Name", "Identity",
    ),
    "sector": FieldDef(
        "ci", "sector", FieldType.TEXT,
        "Sector", "Identity",
    ),
    "industry": FieldDef(
        "ci", "industry", FieldType.TEXT,
        "Industry", "Identity",
    ),
    "market": FieldDef(
        "ci", "market", FieldType.TEXT,
        "Market", "Identity",
    ),
    "currency": FieldDef(
        "ci", "currency", FieldType.TEXT,
        "Currency", "Identity",
    ),
    # tags and ticker_type require PG tables
    # (stock_tags, stock_registry) — not in
    # DuckDB. Planned for v2 via PG subquery.
    # --- Valuation (7) ---
    "market_cap": FieldDef(
        "ci", "market_cap", FieldType.NUMBER,
        "Market Cap", "Valuation",
    ),
    "pe_ratio": FieldDef(
        "ci", "pe_ratio", FieldType.NUMBER,
        "P/E Ratio", "Valuation",
    ),
    "peg_ratio": FieldDef(
        "ci", "peg_ratio", FieldType.NUMBER,
        "PEG (trailing)", "Valuation",
    ),
    "peg_ratio_yf": FieldDef(
        "ci", "peg_ratio_yf", FieldType.NUMBER,
        "PEG (yfinance)", "Valuation",
    ),
    "price_to_book": FieldDef(
        "ci", "price_to_book", FieldType.NUMBER,
        "Price/Book", "Valuation",
    ),
    "dividend_yield": FieldDef(
        "ci", "dividend_yield", FieldType.NUMBER,
        "Dividend Yield", "Valuation",
    ),
    "current_price": FieldDef(
        "ci", "current_price", FieldType.NUMBER,
        "Current Price", "Valuation",
    ),
    "week_52_high": FieldDef(
        "ci", "week_52_high", FieldType.NUMBER,
        "52W High", "Valuation",
    ),
    "week_52_low": FieldDef(
        "ci", "week_52_low", FieldType.NUMBER,
        "52W Low", "Valuation",
    ),
    # --- Profitability (6) ---
    "profit_margins": FieldDef(
        "ci", "profit_margins", FieldType.NUMBER,
        "Profit Margins", "Profitability",
    ),
    "earnings_growth": FieldDef(
        "ci", "earnings_growth", FieldType.NUMBER,
        "Earnings Growth", "Profitability",
    ),
    "revenue_growth": FieldDef(
        "ci", "revenue_growth", FieldType.NUMBER,
        "Revenue Growth", "Profitability",
    ),
    "revenue": FieldDef(
        "qr", "revenue", FieldType.NUMBER,
        "Revenue", "Profitability",
    ),
    "net_income": FieldDef(
        "qr", "net_income", FieldType.NUMBER,
        "Net Income", "Profitability",
    ),
    "eps": FieldDef(
        "qr", "eps_diluted", FieldType.NUMBER,
        "EPS", "Profitability",
    ),
    # --- Risk (5) ---
    "sharpe_ratio": FieldDef(
        "as_", "sharpe_ratio", FieldType.NUMBER,
        "Sharpe Ratio", "Risk",
    ),
    "annualized_return_pct": FieldDef(
        "as_", "annualized_return_pct",
        FieldType.NUMBER,
        "Ann. Return %", "Risk",
    ),
    "annualized_volatility_pct": FieldDef(
        "as_", "annualized_volatility_pct",
        FieldType.NUMBER,
        "Ann. Volatility %", "Risk",
    ),
    "max_drawdown_pct": FieldDef(
        "as_", "max_drawdown_pct", FieldType.NUMBER,
        "Max Drawdown %", "Risk",
    ),
    "beta": FieldDef(
        "ci", "beta", FieldType.NUMBER,
        "Beta", "Risk",
    ),
    # --- Technical (5) ---
    "rsi_14": FieldDef(
        "as_", "rsi_14", FieldType.NUMBER,
        "RSI 14", "Technical",
    ),
    "rsi_signal": FieldDef(
        "as_", "rsi_signal", FieldType.TEXT,
        "RSI Signal", "Technical",
    ),
    "macd_signal": FieldDef(
        "as_", "macd_signal_text", FieldType.TEXT,
        "MACD Signal", "Technical",
    ),
    "sma_200_signal": FieldDef(
        "as_", "sma_200_signal", FieldType.TEXT,
        "SMA 200 Signal", "Technical",
    ),
    "sentiment_score": FieldDef(
        "ss", "avg_score", FieldType.NUMBER,
        "Sentiment Score", "Technical",
    ),
    # --- Quality (3) ---
    "piotroski_score": FieldDef(
        "ps", "total_score", FieldType.NUMBER,
        "Piotroski Score", "Quality",
    ),
    "piotroski_label": FieldDef(
        "ps", "label", FieldType.TEXT,
        "Piotroski Label", "Quality",
    ),
    "forecast_confidence": FieldDef(
        "fr", "confidence_score", FieldType.NUMBER,
        "Forecast Confidence", "Quality",
    ),
    # --- Forecast (3) ---
    "target_3m_pct": FieldDef(
        "fr", "target_3m_pct_change",
        FieldType.NUMBER,
        "3M Target %", "Forecast",
    ),
    "target_6m_pct": FieldDef(
        "fr", "target_6m_pct_change",
        FieldType.NUMBER,
        "6M Target %", "Forecast",
    ),
    "target_9m_pct": FieldDef(
        "fr", "target_9m_pct_change",
        FieldType.NUMBER,
        "9M Target %", "Forecast",
    ),
    # --- Bhavcopy Volume (5) — mirrors AA reports.
    # Computed in `nd` CTE from nse_delivery's
    # traded_qty over latest 25 trading days, anchored
    # to MAX(date) FROM nse_delivery (handles weekends/
    # holidays — see advanced_analytics §5.x).
    "today_vol": FieldDef(
        "nd", "today_vol", FieldType.NUMBER,
        "Today Vol", "Bhavcopy Volume",
    ),
    "avg_20d_vol": FieldDef(
        "nd", "avg_20d_vol", FieldType.NUMBER,
        "Avg 20d Vol", "Bhavcopy Volume",
    ),
    "today_x_vol": FieldDef(
        "nd", "today_x_vol", FieldType.NUMBER,
        "Today × Vol (vs 20d)", "Bhavcopy Volume",
    ),
    "x_vol_10d": FieldDef(
        "nd", "x_vol_10d", FieldType.NUMBER,
        "× Vol (vs 10d)", "Bhavcopy Volume",
    ),
    "x_vol_20d": FieldDef(
        "nd", "x_vol_20d", FieldType.NUMBER,
        "× Vol (vs 20d)", "Bhavcopy Volume",
    ),
    # --- Bhavcopy Delivery (8) — same source.
    # `today_dv` mirrors AA's naming = today's
    # deliverable_qty (a count, not a value).
    "today_dpc": FieldDef(
        "nd", "today_dpc", FieldType.NUMBER,
        "Today DPC %", "Bhavcopy Delivery",
    ),
    "current_dpc": FieldDef(
        "nd", "current_dpc", FieldType.NUMBER,
        "Current DPC %", "Bhavcopy Delivery",
    ),
    "avg_10d_dpc": FieldDef(
        "nd", "avg_10d_dpc", FieldType.NUMBER,
        "Avg 10d DPC %", "Bhavcopy Delivery",
    ),
    "avg_20d_dpc": FieldDef(
        "nd", "avg_20d_dpc", FieldType.NUMBER,
        "Avg 20d DPC %", "Bhavcopy Delivery",
    ),
    "today_dv": FieldDef(
        "nd", "today_dv", FieldType.NUMBER,
        "Today Delivery Qty", "Bhavcopy Delivery",
    ),
    "today_x_dv": FieldDef(
        "nd", "today_x_dv", FieldType.NUMBER,
        "Today × DV (vs 20d)", "Bhavcopy Delivery",
    ),
    "x_dv_10d": FieldDef(
        "nd", "x_dv_10d", FieldType.NUMBER,
        "× DV (vs 10d)", "Bhavcopy Delivery",
    ),
    "x_dv_20d": FieldDef(
        "nd", "x_dv_20d", FieldType.NUMBER,
        "× DV (vs 20d)", "Bhavcopy Delivery",
    ),
    # --- Fundamentals Snapshot (5) — daily aggregator
    # over quarterly_results, table fundamentals_snapshot.
    "sales_3y_cagr": FieldDef(
        "fs", "sales_3y_cagr", FieldType.NUMBER,
        "Sales 3y CAGR", "Fundamentals Snapshot",
    ),
    "prft_3y_cagr": FieldDef(
        "fs", "prft_3y_cagr", FieldType.NUMBER,
        "Profit 3y CAGR", "Fundamentals Snapshot",
    ),
    "roce": FieldDef(
        "fs", "roce", FieldType.NUMBER,
        "ROCE", "Fundamentals Snapshot",
    ),
    "debt_to_eq": FieldDef(
        "fs", "debt_to_eq", FieldType.NUMBER,
        "Debt / Equity", "Fundamentals Snapshot",
    ),
    "yoy_qtr_prft": FieldDef(
        "fs", "yoy_qtr_prft", FieldType.NUMBER,
        "YoY Qtr Profit Growth",
        "Fundamentals Snapshot",
    ),
    # --- Promoter (3) — latest-quarter per ticker
    # from BSE shareholding pattern.
    "prom_hld_pct": FieldDef(
        "ph", "prom_hld_pct", FieldType.NUMBER,
        "Promoter Holding %", "Promoter",
    ),
    "pledged_pct": FieldDef(
        "ph", "pledged_pct", FieldType.NUMBER,
        "Pledged %", "Promoter",
    ),
    "chng_qoq": FieldDef(
        "ph", "chng_qoq", FieldType.NUMBER,
        "Δ Promoter % QoQ", "Promoter",
    ),
    # --- Events (2) — latest event per ticker from
    # NSE corporate-actions feed.
    "latest_event_type": FieldDef(
        "ce", "event_type", FieldType.TEXT,
        "Latest Event Type", "Events",
    ),
    "latest_event_date": FieldDef(
        "ce", "event_date_str", FieldType.TEXT,
        "Latest Event Date", "Events",
    ),
}

NUMERIC_OPS = {">", "<", ">=", "<=", "=", "!="}
TEXT_OPS = {"=", "!=", "LIKE"}
ARRAY_OPS = {"CONTAINS"}
ALL_OPS = NUMERIC_OPS | ARRAY_OPS | {"LIKE"}


def get_field_catalog_json() -> list[dict]:
    """Return field catalog for frontend autocomplete."""
    return [
        {
            "name": name,
            "label": fd.label,
            "type": fd.type.name.lower(),
            "category": fd.category,
        }
        for name, fd in FIELD_CATALOG.items()
    ]


def _suggest_field(name: str) -> str | None:
    matches = difflib.get_close_matches(
        name, FIELD_CATALOG.keys(), n=1, cutoff=0.6,
    )
    return matches[0] if matches else None


# ---------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------


class TokenType(Enum):
    FIELD = auto()
    OP = auto()
    VALUE_NUM = auto()
    VALUE_STR = auto()
    AND = auto()
    OR = auto()
    LPAREN = auto()
    RPAREN = auto()
    CONTAINS = auto()
    LIKE = auto()
    EOF = auto()


@dataclass(slots=True)
class Token:
    type: TokenType
    value: Any
    pos: int


class ScreenQLError(Exception):
    """User-facing parse/validation error."""

    def __init__(self, message: str, pos: int = -1):
        self.pos = pos
        super().__init__(message)


_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<op>>=|<=|!=|>|<|=)          |
        (?P<str>"(?:[^"\\]|\\.)*")      |
        (?P<num>-?\d+(?:\.\d+)?)        |
        (?P<lparen>\()                  |
        (?P<rparen>\))                  |
        (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )\s*
    """,
    re.VERBOSE,
)


def tokenize(query: str) -> list[Token]:
    """Convert query string into token list."""
    # Normalize newlines to AND
    text = query.strip()
    if not text:
        raise ScreenQLError("Query cannot be empty")

    # Replace newlines with AND (implicit AND),
    # but skip if next line already starts with
    # AND/OR to avoid "AND AND" duplication.
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip()
    ]
    parts: list[str] = []
    for ln in lines:
        upper = ln.upper()
        if parts and not (
            upper.startswith("AND ")
            or upper.startswith("OR ")
        ):
            parts.append("AND")
        parts.append(ln)
    text = " ".join(parts)

    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ScreenQLError(
                f"Unexpected character at position "
                f"{pos}: '{text[pos]}'",
                pos,
            )
        if m.group("op"):
            tokens.append(Token(
                TokenType.OP, m.group("op"), pos,
            ))
        elif m.group("str"):
            # Strip quotes
            raw = m.group("str")[1:-1]
            raw = raw.replace('\\"', '"')
            tokens.append(Token(
                TokenType.VALUE_STR, raw, pos,
            ))
        elif m.group("num"):
            val = m.group("num")
            num = float(val) if "." in val else int(val)
            tokens.append(Token(
                TokenType.VALUE_NUM, num, pos,
            ))
        elif m.group("lparen"):
            tokens.append(Token(
                TokenType.LPAREN, "(", pos,
            ))
        elif m.group("rparen"):
            tokens.append(Token(
                TokenType.RPAREN, ")", pos,
            ))
        elif m.group("word"):
            word = m.group("word")
            upper = word.upper()
            if upper == "AND":
                tokens.append(Token(
                    TokenType.AND, "AND", pos,
                ))
            elif upper == "OR":
                tokens.append(Token(
                    TokenType.OR, "OR", pos,
                ))
            elif upper == "CONTAINS":
                tokens.append(Token(
                    TokenType.CONTAINS, "CONTAINS",
                    pos,
                ))
            elif upper == "LIKE":
                tokens.append(Token(
                    TokenType.LIKE, "LIKE", pos,
                ))
            else:
                tokens.append(Token(
                    TokenType.FIELD, word, pos,
                ))
        pos = m.end()

    tokens.append(Token(TokenType.EOF, None, pos))
    return tokens


# ---------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------


@dataclass(slots=True)
class Condition:
    field_name: str
    operator: str
    value: Any
    field_def: FieldDef


@dataclass(slots=True)
class BinaryOp:
    op: str  # "AND" or "OR"
    left: "ASTNode"
    right: "ASTNode"


ASTNode = Condition | BinaryOp


# ---------------------------------------------------------------
# Recursive descent parser
# ---------------------------------------------------------------


class Parser:
    """Parse token stream into AST."""

    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0
        self._condition_count = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        t = self._tokens[self._pos]
        self._pos += 1
        return t

    def _expect(
        self, tt: TokenType, msg: str,
    ) -> Token:
        t = self._peek()
        if t.type != tt:
            raise ScreenQLError(msg, t.pos)
        return self._advance()

    def parse(self) -> ASTNode:
        node = self._parse_or()
        if self._peek().type != TokenType.EOF:
            t = self._peek()
            raise ScreenQLError(
                f"Unexpected token at position "
                f"{t.pos}: '{t.value}'",
                t.pos,
            )
        return node

    def _parse_or(self) -> ASTNode:
        left = self._parse_and()
        while self._peek().type == TokenType.OR:
            self._advance()
            right = self._parse_and()
            left = BinaryOp("OR", left, right)
        return left

    def _parse_and(self) -> ASTNode:
        left = self._parse_atom()
        while self._peek().type == TokenType.AND:
            self._advance()
            right = self._parse_atom()
            left = BinaryOp("AND", left, right)
        return left

    def _parse_atom(self) -> ASTNode:
        t = self._peek()
        if t.type == TokenType.LPAREN:
            self._advance()
            node = self._parse_or()
            self._expect(
                TokenType.RPAREN,
                f"Expected ')' at position "
                f"{self._peek().pos}",
            )
            return node
        return self._parse_condition()

    def _parse_condition(self) -> Condition:
        self._condition_count += 1
        if self._condition_count > MAX_CONDITIONS:
            raise ScreenQLError(
                f"Maximum {MAX_CONDITIONS} "
                f"conditions per query",
            )

        field_tok = self._expect(
            TokenType.FIELD,
            f"Expected field name at position "
            f"{self._peek().pos}",
        )
        field_name = field_tok.value.lower()

        # Validate field exists
        if field_name not in FIELD_CATALOG:
            suggestion = _suggest_field(field_name)
            msg = (
                f"Unknown field: {field_tok.value}"
            )
            if suggestion:
                msg += f". Did you mean: {suggestion}?"
            raise ScreenQLError(msg, field_tok.pos)

        fd = FIELD_CATALOG[field_name]

        # Parse operator
        t = self._peek()
        if t.type == TokenType.CONTAINS:
            op = "CONTAINS"
            self._advance()
        elif t.type == TokenType.LIKE:
            op = "LIKE"
            self._advance()
        elif t.type == TokenType.OP:
            op = t.value
            self._advance()
        else:
            raise ScreenQLError(
                f"Expected operator after "
                f"'{field_name}' at position "
                f"{t.pos}",
                t.pos,
            )

        # Validate operator for field type
        if fd.type == FieldType.NUMBER:
            if op not in NUMERIC_OPS:
                raise ScreenQLError(
                    f"Cannot use {op} with number "
                    f"field '{field_name}'",
                    t.pos,
                )
        elif fd.type == FieldType.TEXT:
            if op not in TEXT_OPS:
                raise ScreenQLError(
                    f"Cannot use {op} with text "
                    f"field '{field_name}'. "
                    f"Use = or !=",
                    t.pos,
                )
        elif fd.type == FieldType.ARRAY:
            if op not in ARRAY_OPS:
                raise ScreenQLError(
                    f"Use CONTAINS with array "
                    f"field '{field_name}'",
                    t.pos,
                )

        # Parse value
        vt = self._peek()
        if fd.type == FieldType.NUMBER:
            if vt.type != TokenType.VALUE_NUM:
                raise ScreenQLError(
                    f"Expected number after "
                    f"'{field_name} {op}' at "
                    f"position {vt.pos}",
                    vt.pos,
                )
            value = vt.value
            self._advance()
        elif fd.type in (
            FieldType.TEXT, FieldType.ARRAY,
        ):
            if vt.type != TokenType.VALUE_STR:
                raise ScreenQLError(
                    f'Expected quoted string after '
                    f"'{field_name} {op}' at "
                    f"position {vt.pos}",
                    vt.pos,
                )
            value = vt.value
            self._advance()
        else:
            raise ScreenQLError(
                f"Unexpected value at position "
                f"{vt.pos}",
                vt.pos,
            )

        return Condition(field_name, op, value, fd)


def parse_query(query: str) -> ASTNode:
    """Parse a ScreenQL query string into an AST."""
    tokens = tokenize(query)
    parser = Parser(tokens)
    return parser.parse()


# ---------------------------------------------------------------
# SQL generator
# ---------------------------------------------------------------

# CTE definitions for each table alias
_CTE_TEMPLATES: dict[str, str] = {
    "ci": (
        "ci_raw AS (\n"
        "  SELECT *,\n"
        # Market classification — authoritative source
        # is yfinance's `exchange` field stored on
        # `company_info` (CLAUDE.md Rule 19: don't
        # reinvent classification locally). Yahoo
        # returns internal codes, not "NSE"/"BSE":
        #   NSI = NSE, BSE = BSE (both → india)
        #   NMS/NYQ/SNP/CXI/… → us
        # Fallbacks preserve behaviour on rows missing
        # `exchange` (current warehouse has ~13 NaN):
        #   1. `.NS`/`.BO` suffix → india
        #   2. Known Indian index tickers → india
        #   3. Otherwise → us
        # Long-term fix (separate ticket): materialise
        # a `market` column on company_info at write
        # time via detect_market() and read it here
        # directly.
        "    CASE\n"
        "      WHEN exchange IN ('NSI', 'BSE')\n"
        "        THEN 'india'\n"
        "      WHEN exchange IS NOT NULL\n"
        "        AND exchange != ''\n"
        "        THEN 'us'\n"
        "      WHEN ticker LIKE '%.NS'\n"
        "        OR ticker LIKE '%.BO'\n"
        "        THEN 'india'\n"
        "      WHEN ticker IN (\n"
        "        '^NSEI', '^BSESN', '^INDIAVIX'\n"
        "      ) THEN 'india'\n"
        "      ELSE 'us'\n"
        "    END AS market,\n"
        # PEG = P/E divided by growth%. Undefined for
        # loss-makers (pe_ratio<=0) or declining-
        # earnings stocks (earnings_growth<=0) — they
        # return NULL rather than a garbage value.
        "    CASE\n"
        "      WHEN pe_ratio IS NULL\n"
        "        OR pe_ratio <= 0\n"
        "        THEN NULL\n"
        "      WHEN earnings_growth IS NULL\n"
        "        OR earnings_growth <= 0\n"
        "        THEN NULL\n"
        "      ELSE pe_ratio\n"
        "        / (earnings_growth * 100.0)\n"
        "    END AS peg_ratio,\n"
        "    ROW_NUMBER() OVER (\n"
        "      PARTITION BY ticker\n"
        "      ORDER BY fetched_at DESC\n"
        "    ) AS rn\n"
        "  FROM company_info\n"
        "),\n"
        "ci AS (\n"
        "  SELECT * FROM ci_raw WHERE rn = 1\n"
        ")"
    ),
    "as_": (
        "as_raw AS (\n"
        "  SELECT *,\n"
        "    TRY_CAST(\n"
        "      regexp_extract(\n"
        "        rsi_signal, 'RSI:\\s*([\\d.]+)',1\n"
        "      ) AS DOUBLE\n"
        "    ) AS rsi_14,\n"
        "    ROW_NUMBER() OVER (\n"
        "      PARTITION BY ticker\n"
        "      ORDER BY computed_at DESC\n"
        "    ) AS rn\n"
        "  FROM analysis_summary\n"
        "),\n"
        "as_ AS (\n"
        "  SELECT * FROM as_raw WHERE rn = 1\n"
        ")"
    ),
    "ps": (
        "ps_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY score_date DESC\n"
        "  ) AS rn FROM piotroski_scores\n"
        "),\n"
        "ps AS (\n"
        "  SELECT * FROM ps_raw WHERE rn = 1\n"
        ")"
    ),
    "fr": (
        "fr_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY computed_at DESC\n"
        "  ) AS rn FROM forecast_runs\n"
        "  WHERE horizon_months != 0\n"
        "),\n"
        "fr AS (\n"
        "  SELECT * FROM fr_raw WHERE rn = 1\n"
        ")"
    ),
    "ss": (
        "ss_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY score_date DESC\n"
        "  ) AS rn FROM sentiment_scores\n"
        "),\n"
        "ss AS (\n"
        "  SELECT * FROM ss_raw WHERE rn = 1\n"
        ")"
    ),
    "qr": (
        "qr_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY quarter_end DESC\n"
        "  ) AS rn FROM quarterly_results\n"
        "  WHERE statement_type = 'income'\n"
        "),\n"
        "qr AS (\n"
        "  SELECT * FROM qr_raw WHERE rn = 1\n"
        ")"
    ),
    # Bhavcopy delivery aggregates — anchored to MAX(date)
    # FROM nse_delivery so "today" matches the AA reports
    # (handles weekends / public holidays). Single window
    # pass over latest 25 days per ticker; aggregates +
    # derived ratios in two stages.
    "nd": (
        "nd_anchor AS (\n"
        "  SELECT MAX(date) AS as_of FROM nse_delivery\n"
        "),\n"
        "nd_raw AS (\n"
        "  SELECT d.*, ROW_NUMBER() OVER (\n"
        "    PARTITION BY d.ticker\n"
        "    ORDER BY d.date DESC\n"
        "  ) AS rn\n"
        "  FROM nse_delivery d\n"
        "  CROSS JOIN nd_anchor a\n"
        "  WHERE d.date <= a.as_of\n"
        "),\n"
        "nd_agg AS (\n"
        "  SELECT ticker,\n"
        "    MAX(CASE WHEN rn=1 THEN delivery_pct END)\n"
        "      AS today_dpc,\n"
        "    AVG(CASE WHEN rn<=10 THEN delivery_pct END)\n"
        "      AS avg_10d_dpc,\n"
        "    AVG(CASE WHEN rn<=20 THEN delivery_pct END)\n"
        "      AS avg_20d_dpc,\n"
        "    MAX(CASE WHEN rn=1 THEN deliverable_qty END)\n"
        "      AS today_dv,\n"
        "    AVG(CASE WHEN rn<=10 THEN deliverable_qty END)\n"
        "      AS avg_10d_dv,\n"
        "    AVG(CASE WHEN rn<=20 THEN deliverable_qty END)\n"
        "      AS avg_20d_dv,\n"
        "    MAX(CASE WHEN rn=1 THEN traded_qty END)\n"
        "      AS today_vol,\n"
        "    AVG(CASE WHEN rn<=10 THEN traded_qty END)\n"
        "      AS avg_10d_vol,\n"
        "    AVG(CASE WHEN rn<=20 THEN traded_qty END)\n"
        "      AS avg_20d_vol\n"
        "  FROM nd_raw WHERE rn <= 25\n"
        "  GROUP BY ticker\n"
        "),\n"
        "nd AS (\n"
        "  SELECT *,\n"
        "    today_dpc AS current_dpc,\n"
        "    today_vol / NULLIF(avg_20d_vol, 0)\n"
        "      AS today_x_vol,\n"
        "    today_vol / NULLIF(avg_10d_vol, 0)\n"
        "      AS x_vol_10d,\n"
        "    today_vol / NULLIF(avg_20d_vol, 0)\n"
        "      AS x_vol_20d,\n"
        "    today_dv / NULLIF(avg_20d_dv, 0)\n"
        "      AS today_x_dv,\n"
        "    today_dv / NULLIF(avg_10d_dv, 0)\n"
        "      AS x_dv_10d,\n"
        "    today_dv / NULLIF(avg_20d_dv, 0)\n"
        "      AS x_dv_20d\n"
        "  FROM nd_agg\n"
        ")"
    ),
    # Daily fundamentals snapshot — latest per ticker.
    "fs": (
        "fs_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY snapshot_date DESC\n"
        "  ) AS rn FROM fundamentals_snapshot\n"
        "),\n"
        "fs AS (\n"
        "  SELECT * FROM fs_raw WHERE rn = 1\n"
        ")"
    ),
    # Promoter holdings — latest quarter per ticker.
    "ph": (
        "ph_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY quarter_end DESC\n"
        "  ) AS rn FROM promoter_holdings\n"
        "),\n"
        "ph AS (\n"
        "  SELECT * FROM ph_raw WHERE rn = 1\n"
        ")"
    ),
    # Latest corporate event per ticker (the AA tab uses
    # event_label || event_type; here we expose just the
    # event_type for queryability + a string-coerced date
    # so the TEXT-only operators apply consistently).
    "ce": (
        "ce_raw AS (\n"
        "  SELECT *, ROW_NUMBER() OVER (\n"
        "    PARTITION BY ticker\n"
        "    ORDER BY event_date DESC\n"
        "  ) AS rn FROM corporate_events\n"
        "),\n"
        "ce AS (\n"
        "  SELECT ticker, event_type,\n"
        "    CAST(event_date AS VARCHAR)\n"
        "      AS event_date_str\n"
        "  FROM ce_raw WHERE rn = 1\n"
        ")"
    ),
}

# Base columns always returned
BASE_COLUMNS = [
    ("ci", "ticker"),
    ("ci", "company_name"),
    ("ci", "sector"),
    ("ci", "market_cap"),
    ("ci", "current_price"),
    ("ci", "currency"),
]


def _collect_tables(node: ASTNode) -> set[str]:
    """Collect all table aliases from the AST."""
    if isinstance(node, Condition):
        return {node.field_def.table}
    return (
        _collect_tables(node.left)
        | _collect_tables(node.right)
    )


def _collect_fields(node: ASTNode) -> list[str]:
    """Collect field names used in conditions."""
    if isinstance(node, Condition):
        return [node.field_name]
    return (
        _collect_fields(node.left)
        + _collect_fields(node.right)
    )


def _build_where(
    node: ASTNode,
    params: list[Any],
) -> str:
    """Build WHERE clause from AST, appending
    parameterized values to params list."""
    if isinstance(node, BinaryOp):
        left = _build_where(node.left, params)
        right = _build_where(node.right, params)
        return f"({left} {node.op} {right})"

    c = node
    tbl = c.field_def.table
    col = c.field_def.column

    if c.operator == "CONTAINS":
        # tags: EXISTS subquery
        params.append(c.value)
        idx = len(params)
        return (
            f"EXISTS (SELECT 1 FROM st "
            f"WHERE st.ticker = ci.ticker "
            f"AND st.tag = ${idx})"
        )

    if c.operator == "LIKE":
        # Case-insensitive substring search. Wrap the
        # raw value with %s so the user types the bare
        # substring (e.g. `ticker LIKE "RELIA"`).
        # Underscore + backslash are SQL LIKE
        # metacharacters; escape so the user-supplied
        # string is treated literally.
        raw = str(c.value)
        escaped = (
            raw.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        params.append(f"%{escaped}%")
        idx = len(params)
        qual = f"{tbl}.{col}"
        return (
            f"({qual} IS NOT NULL AND "
            f"LOWER({qual}) LIKE LOWER(${idx}) "
            f"ESCAPE '\\')"
        )

    # NULL-safe: field IS NOT NULL AND field op $N
    params.append(c.value)
    idx = len(params)
    qual = f"{tbl}.{col}"
    return (
        f"({qual} IS NOT NULL AND "
        f"{qual} {c.operator} ${idx})"
    )


@dataclass
class GeneratedQuery:
    """Result of SQL generation."""
    sql: str
    count_sql: str
    params: list[Any]
    columns_used: list[str]
    tables_used: set[str]


def generate_sql(
    ast: ASTNode,
    page: int = 1,
    page_size: int = 25,
    sort_by: str | None = None,
    sort_dir: str = "desc",
    ticker_filter: list[str] | None = None,
    display_columns: list[str] | None = None,
) -> GeneratedQuery:
    """Generate DuckDB SQL from parsed AST.

    ``display_columns`` (ASETPLTFRM-333): optional list
    of field names to add to the SELECT beyond what the
    WHERE references. Lets the UI column selector
    expose fields like ``piotroski_score`` or ``eps``
    in results even when they're not part of the
    filter. Unknown / unregistered field names are
    silently ignored.
    """
    tables = _collect_tables(ast)
    fields_used = _collect_fields(ast)

    # Always need ci for base columns
    tables.add("ci")

    # Merge display-only columns into the field set,
    # preserving filter-referenced columns first so the
    # SELECT ordering stays predictable for the UI.
    if display_columns:
        extra: list[str] = []
        seen = set(fields_used)
        for name in display_columns:
            if name in FIELD_CATALOG and name not in seen:
                extra.append(name)
                seen.add(name)
                fd = FIELD_CATALOG[name]
                if fd.table != "st":
                    tables.add(fd.table)
        fields_used = [*fields_used, *extra]

    # Build params
    params: list[Any] = []
    where_clause = _build_where(ast, params)

    # Ticker filter (user scope)
    if ticker_filter is not None:
        placeholders = ", ".join(
            f"${len(params) + i + 1}"
            for i in range(len(ticker_filter))
        )
        params.extend(ticker_filter)
        where_clause = (
            f"({where_clause}) AND "
            f"ci.ticker IN ({placeholders})"
        )

    # CTEs — only include referenced tables
    ctes: list[str] = []
    for alias in (
        "ci", "as_", "ps", "fr", "ss", "qr",
        "nd", "fs", "ph", "ce",
    ):
        if alias in tables:
            ctes.append(_CTE_TEMPLATES[alias])

    cte_sql = "WITH " + ",\n".join(ctes)

    # SELECT columns: base + query fields
    select_cols: list[str] = []
    seen: set[str] = set()
    for tbl, col in BASE_COLUMNS:
        key = f"{tbl}.{col}"
        if key not in seen:
            select_cols.append(key)
            seen.add(key)

    for fname in fields_used:
        fd = FIELD_CATALOG[fname]
        if fd.table == "st":
            continue  # tags handled via EXISTS
        key = f"{fd.table}.{fd.column}"
        if key not in seen:
            select_cols.append(
                f"{key} AS {fname}",
            )
            seen.add(key)

    select_str = ", ".join(select_cols)

    # JOINs
    joins: list[str] = []
    if "as_" in tables:
        joins.append(
            "LEFT JOIN as_ "
            "ON as_.ticker = ci.ticker",
        )
    if "ps" in tables:
        joins.append(
            "LEFT JOIN ps "
            "ON ps.ticker = ci.ticker",
        )
    if "fr" in tables:
        joins.append(
            "LEFT JOIN fr "
            "ON fr.ticker = ci.ticker",
        )
    if "ss" in tables:
        joins.append(
            "LEFT JOIN ss "
            "ON ss.ticker = ci.ticker",
        )
    if "qr" in tables:
        joins.append(
            "LEFT JOIN qr "
            "ON qr.ticker = ci.ticker",
        )
    if "nd" in tables:
        joins.append(
            "LEFT JOIN nd "
            "ON nd.ticker = ci.ticker",
        )
    if "fs" in tables:
        joins.append(
            "LEFT JOIN fs "
            "ON fs.ticker = ci.ticker",
        )
    if "ph" in tables:
        joins.append(
            "LEFT JOIN ph "
            "ON ph.ticker = ci.ticker",
        )
    if "ce" in tables:
        joins.append(
            "LEFT JOIN ce "
            "ON ce.ticker = ci.ticker",
        )
    join_str = "\n".join(joins)

    # Sort
    if sort_by and sort_by in FIELD_CATALOG:
        sfd = FIELD_CATALOG[sort_by]
        if sfd.table == "st":
            order = "ci.ticker"
        else:
            order = f"{sfd.table}.{sfd.column}"
    elif sort_by == "company_name":
        order = "ci.company_name"
    elif sort_by == "current_price":
        order = "ci.current_price"
    else:
        order = "ci.market_cap"

    direction = (
        "ASC" if sort_dir == "asc" else "DESC"
    )
    order_clause = (
        f"{order} {direction} NULLS LAST"
    )

    # Pagination
    offset = (page - 1) * page_size
    params.append(page_size)
    limit_idx = len(params)
    params.append(offset)
    offset_idx = len(params)

    sql = (
        f"{cte_sql}\n"
        f"SELECT {select_str}\n"
        f"FROM ci\n"
        f"{join_str}\n"
        f"WHERE {where_clause}\n"
        f"ORDER BY {order_clause}\n"
        f"LIMIT ${limit_idx} OFFSET ${offset_idx}"
    )

    # Count query (no ORDER/LIMIT)
    count_sql = (
        f"{cte_sql}\n"
        f"SELECT COUNT(*) AS cnt\n"
        f"FROM ci\n"
        f"{join_str}\n"
        f"WHERE {where_clause}"
    )

    # Dedupe fields_used preserving order
    unique_fields: list[str] = []
    for f in fields_used:
        if f not in unique_fields:
            unique_fields.append(f)

    return GeneratedQuery(
        sql=sql,
        count_sql=count_sql,
        params=params,
        columns_used=unique_fields,
        tables_used=tables,
    )


# ---------------------------------------------------------------
# Tables sub-mode — query a single Iceberg table directly.
# Reuses the same WHERE-clause parser (Parser class) but with a
# per-table column whitelist instead of FIELD_CATALOG. Hard
# LIMIT cap (1000) prevents accidental full-table scans.
# ---------------------------------------------------------------

TABLE_LIMIT_MAX = 1000
TABLE_LIMIT_DEFAULT = 100

# Per-table column whitelist. Columns are declared with their
# logical type; date columns ride as TEXT (use `LIKE "2026-04"`
# for substring time filters in v1; numeric range comes later).
TABLE_CATALOG: dict[str, dict[str, FieldType]] = {
    "nse_delivery": {
        "ticker": FieldType.TEXT,
        "date": FieldType.TEXT,
        "deliverable_qty": FieldType.NUMBER,
        "delivery_pct": FieldType.NUMBER,
        "traded_qty": FieldType.NUMBER,
        "traded_value": FieldType.NUMBER,
    },
    "fundamentals_snapshot": {
        "ticker": FieldType.TEXT,
        "snapshot_date": FieldType.TEXT,
        "sales_3y_cagr": FieldType.NUMBER,
        "prft_3y_cagr": FieldType.NUMBER,
        "sales_5y_cagr": FieldType.NUMBER,
        "prft_5y_cagr": FieldType.NUMBER,
        "yoy_qtr_prft": FieldType.NUMBER,
        "yoy_qtr_sales": FieldType.NUMBER,
        "roce": FieldType.NUMBER,
        "debt_to_eq": FieldType.NUMBER,
    },
    "corporate_events": {
        "ticker": FieldType.TEXT,
        "event_date": FieldType.TEXT,
        "event_type": FieldType.TEXT,
        "event_label": FieldType.TEXT,
    },
    "promoter_holdings": {
        "ticker": FieldType.TEXT,
        "quarter_end": FieldType.TEXT,
        "prom_hld_pct": FieldType.NUMBER,
        "pledged_pct": FieldType.NUMBER,
        "chng_qoq": FieldType.NUMBER,
        "source": FieldType.TEXT,
    },
    "ohlcv": {
        "ticker": FieldType.TEXT,
        "date": FieldType.TEXT,
        "open": FieldType.NUMBER,
        "high": FieldType.NUMBER,
        "low": FieldType.NUMBER,
        "close": FieldType.NUMBER,
        "volume": FieldType.NUMBER,
    },
    "dividends": {
        "ticker": FieldType.TEXT,
        "ex_date": FieldType.TEXT,
        "amount": FieldType.NUMBER,
    },
    "quarterly_results": {
        "ticker": FieldType.TEXT,
        "quarter_end": FieldType.TEXT,
        "statement_type": FieldType.TEXT,
        "revenue": FieldType.NUMBER,
        "net_income": FieldType.NUMBER,
        "eps_diluted": FieldType.NUMBER,
    },
}


def get_table_catalog_json() -> list[dict]:
    """Return the table-mode catalog for the frontend."""
    out: list[dict] = []
    for tbl, cols in TABLE_CATALOG.items():
        out.append({
            "name": tbl,
            "iceberg": f"stocks.{tbl}",
            "columns": [
                {"name": c, "type": t.name.lower()}
                for c, t in cols.items()
            ],
        })
    return out


def _build_table_field_map(
    table: str,
) -> dict[str, FieldDef]:
    """Synthesize a field catalog for the picked table.

    Lets us reuse the existing :class:`Parser` (which
    validates against ``FIELD_CATALOG``) by swapping in a
    per-table catalog. The :class:`FieldDef.table` value is
    the actual physical table name so ``_build_where`` emits
    ``nse_delivery.delivery_pct > $1`` correctly.
    """
    if table not in TABLE_CATALOG:
        raise ScreenQLError(
            f"Unknown table: {table}",
        )
    return {
        col: FieldDef(
            table=table,
            column=col,
            type=ftype,
            label=col,
            category=table,
        )
        for col, ftype in TABLE_CATALOG[table].items()
    }


def parse_table_query(
    where: str, table: str,
) -> ASTNode | None:
    """Parse a Tables-mode WHERE clause.

    Empty / whitespace-only ``where`` returns ``None`` (no
    filter — the SQL generator emits an unfiltered SELECT
    capped by ``LIMIT``). Otherwise the same DSL grammar
    as the screen mode applies, but field names must
    belong to the picked table.
    """
    if not where or not where.strip():
        return None
    field_map = _build_table_field_map(table)
    tokens = tokenize(where)
    # Patch _parse_condition's reference to FIELD_CATALOG
    # via a module-level swap — Parser doesn't yet take
    # a catalog arg. Restore on exit.
    parser = _TableParser(tokens, field_map)
    return parser.parse()


class _TableParser(Parser):
    """Parser variant that validates fields against a
    table-scoped catalog instead of ``FIELD_CATALOG``."""

    def __init__(
        self,
        tokens: list[Token],
        catalog: dict[str, FieldDef],
    ):
        super().__init__(tokens)
        self._catalog = catalog

    def _parse_condition(self) -> Condition:
        # Re-implement just the field-validation step;
        # the rest (operator + value parse) is identical
        # to the parent.
        self._condition_count += 1
        if self._condition_count > MAX_CONDITIONS:
            raise ScreenQLError(
                f"Maximum {MAX_CONDITIONS} "
                f"conditions per query",
            )

        field_tok = self._expect(
            TokenType.FIELD,
            f"Expected field name at position "
            f"{self._peek().pos}",
        )
        field_name = field_tok.value.lower()

        if field_name not in self._catalog:
            matches = difflib.get_close_matches(
                field_name,
                self._catalog.keys(),
                n=1,
                cutoff=0.6,
            )
            msg = f"Unknown column: {field_tok.value}"
            if matches:
                msg += f". Did you mean: {matches[0]}?"
            raise ScreenQLError(msg, field_tok.pos)

        fd = self._catalog[field_name]

        t = self._peek()
        if t.type == TokenType.CONTAINS:
            op = "CONTAINS"
            self._advance()
        elif t.type == TokenType.LIKE:
            op = "LIKE"
            self._advance()
        elif t.type == TokenType.OP:
            op = t.value
            self._advance()
        else:
            raise ScreenQLError(
                f"Expected operator after "
                f"'{field_name}' at position "
                f"{t.pos}",
                t.pos,
            )

        if fd.type == FieldType.NUMBER:
            if op not in NUMERIC_OPS:
                raise ScreenQLError(
                    f"Cannot use {op} with number "
                    f"column '{field_name}'",
                    t.pos,
                )
        elif fd.type == FieldType.TEXT:
            if op not in TEXT_OPS:
                raise ScreenQLError(
                    f"Cannot use {op} with text "
                    f"column '{field_name}'. "
                    f"Use =, !=, or LIKE",
                    t.pos,
                )

        vt = self._peek()
        if fd.type == FieldType.NUMBER:
            if vt.type != TokenType.VALUE_NUM:
                raise ScreenQLError(
                    f"Expected number after "
                    f"'{field_name} {op}' at "
                    f"position {vt.pos}",
                    vt.pos,
                )
            value = vt.value
        else:
            if vt.type != TokenType.VALUE_STR:
                raise ScreenQLError(
                    f'Expected quoted string after '
                    f"'{field_name} {op}' at "
                    f"position {vt.pos}",
                    vt.pos,
                )
            value = vt.value
        self._advance()
        return Condition(field_name, op, value, fd)


def generate_table_sql(
    table: str,
    ast: ASTNode | None,
    sort_by: str | None = None,
    sort_dir: str = "desc",
    limit: int = TABLE_LIMIT_DEFAULT,
    offset: int = 0,
    ticker_filter: list[str] | None = None,
) -> GeneratedQuery:
    """Generate DuckDB SQL for the Tables sub-mode.

    Single-table SELECT — no CTEs, no JOINs. *limit* is
    clamped to ``TABLE_LIMIT_MAX``. *sort_by* must be one
    of the table's columns; falls back to ``ticker`` if
    not provided. *ticker_filter* (when given) injects
    ``WHERE ticker IN (...)`` so general users still see
    their watchlist + holdings only.
    """
    if table not in TABLE_CATALOG:
        raise ScreenQLError(
            f"Unknown table: {table}",
        )
    cols = TABLE_CATALOG[table]
    limit_capped = max(
        1, min(int(limit), TABLE_LIMIT_MAX),
    )
    offset_capped = max(0, int(offset))

    params: list[Any] = []
    where_clause = ""
    if ast is not None:
        where_clause = _build_where(ast, params)

    # Ticker scope filter — only if the table has a
    # ticker column (all whitelisted tables do, but
    # be defensive).
    if ticker_filter is not None and "ticker" in cols:
        placeholders = ", ".join(
            f"${len(params) + i + 1}"
            for i in range(len(ticker_filter))
        )
        params.extend(ticker_filter)
        scope = f"{table}.ticker IN ({placeholders})"
        where_clause = (
            f"({where_clause}) AND {scope}"
            if where_clause
            else scope
        )

    # SELECT projection — every whitelisted column,
    # casting dates to VARCHAR so JSON serialization is
    # deterministic.
    select_parts: list[str] = []
    for col, ftype in cols.items():
        if ftype is FieldType.TEXT and (
            "date" in col or col == "quarter_end"
        ):
            select_parts.append(
                f"CAST({table}.{col} AS VARCHAR) AS {col}"
            )
        else:
            select_parts.append(f"{table}.{col}")
    select_str = ", ".join(select_parts)

    # ORDER BY — fall back to ticker if sort_by not in
    # the column whitelist.
    if sort_by and sort_by in cols:
        order_col = f"{table}.{sort_by}"
    else:
        order_col = f"{table}.ticker"
    direction = (
        "ASC" if sort_dir == "asc" else "DESC"
    )

    where_sql = (
        f"WHERE {where_clause}\n" if where_clause else ""
    )

    params.append(limit_capped)
    limit_idx = len(params)
    params.append(offset_capped)
    offset_idx = len(params)

    sql = (
        f"SELECT {select_str}\n"
        f"FROM {table}\n"
        f"{where_sql}"
        f"ORDER BY {order_col} {direction} NULLS LAST\n"
        f"LIMIT ${limit_idx} OFFSET ${offset_idx}"
    )
    count_sql = (
        f"SELECT COUNT(*) AS cnt FROM {table}\n"
        f"{where_sql}"
    )

    return GeneratedQuery(
        sql=sql,
        count_sql=count_sql,
        params=params,
        columns_used=list(cols.keys()),
        tables_used={table},
    )
