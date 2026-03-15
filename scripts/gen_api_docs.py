"""Auto-generate API reference docs from FastAPI routes.

Called by ``mkdocs-gen-files`` during ``mkdocs build`` / ``mkdocs serve``.
Outputs ``docs/backend/api-reference.md`` (never committed).

Usage (standalone test)::

    python scripts/gen_api_docs.py
"""

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parent.parent
_BACKEND = _PROJECT / "backend"
for _p in (str(_BACKEND), str(_PROJECT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Silence startup logs during doc generation.
import os  # noqa: E402

os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("JWT_SECRET_KEY", "docgen-placeholder-key-not-real")


def _auth_label(deps: list) -> str:
    """Map FastAPI dependency names to auth labels."""
    names = [
        getattr(d, "__name__", str(d))
        for d in (deps or [])
    ]
    if any("superuser" in n for n in names):
        return "superuser"
    if any("current_user" in n for n in names):
        return "authenticated"
    return "public"


def _generate() -> str:
    """Introspect FastAPI app and build markdown."""
    from main import app

    lines = [
        "# API Reference (Auto-Generated)",
        "",
        "!!! info",
        "    This page is auto-generated from FastAPI "
        "route definitions on every `mkdocs build`.",
        "    Do not edit manually.",
        "",
    ]

    # Group routes by prefix.
    groups: dict[str, list[dict]] = {}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        path = getattr(route, "path", "")
        if path in ("/openapi.json", "/docs", "/redoc"):
            continue

        # Determine group.
        if "/admin/" in path:
            group = "Admin"
        elif "/auth/" in path:
            group = "Auth"
        elif "/users/" in path:
            group = "Users"
        elif "/bulk" in path:
            group = "Bulk Data"
        elif "/ws/" in path:
            group = "WebSocket"
        else:
            group = "Core"

        deps = getattr(route, "dependencies", [])
        dep_callables = [
            d.dependency for d in deps
            if hasattr(d, "dependency")
        ]
        # Also check endpoint-level dependencies.
        endpoint = getattr(route, "endpoint", None)
        ep_deps = getattr(
            endpoint, "__dependencies__", []
        )
        all_deps = dep_callables + list(ep_deps)

        for method in sorted(methods):
            if method == "HEAD":
                continue
            groups.setdefault(group, []).append({
                "method": method,
                "path": path,
                "name": getattr(
                    route, "name", ""
                ),
                "summary": getattr(
                    route, "summary", ""
                ) or "",
                "auth": _auth_label(all_deps),
            })

    # Render tables.
    order = [
        "Core", "Auth", "Users", "Admin",
        "Bulk Data", "WebSocket",
    ]
    for grp in order:
        routes = groups.get(grp)
        if not routes:
            continue
        lines.append(f"## {grp}\n")
        lines.append(
            "| Method | Path | Auth | Description |"
        )
        lines.append(
            "|--------|------|------|-------------|"
        )
        for r in sorted(routes, key=lambda x: x["path"]):
            desc = r["summary"] or r["name"]
            lines.append(
                f"| `{r['method']}` "
                f"| `{r['path']}` "
                f"| {r['auth']} "
                f"| {desc} |"
            )
        lines.append("")

    # Count.
    total = sum(len(v) for v in groups.values())
    lines.append(f"---\n\n*{total} endpoints total.*\n")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(_generate())
else:
    # Called by mkdocs-gen-files.
    try:
        import mkdocs_gen_files  # noqa: F401

        content = _generate()
        with mkdocs_gen_files.open(
            "backend/api-reference.md", "w"
        ) as f:
            f.write(content)
    except ImportError:
        pass
