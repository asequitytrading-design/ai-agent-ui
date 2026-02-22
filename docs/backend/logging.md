# Logging

Structured logging is configured in `backend/logging_config.py`. A single call to `setup_logging()` at startup configures the root Python logger, which all child loggers (one per module) inherit automatically.

---

## Setup

```python
from logging_config import setup_logging

setup_logging(
    level="DEBUG",       # Minimum severity to emit
    log_to_file=True,    # Also write to a rotating file
    log_dir="logs",      # Directory for the log file (relative to cwd)
)
```

This is called once at the very top of the startup sequence in `main.py`, before `ChatServer` is instantiated, so all subsequent log calls throughout the application are captured.

---

## Log Format

All handlers share a single format string:

```
YYYY-MM-DD HH:MM:SS,mmm | LEVEL    | logger.name | message
```

Example lines:

```
2026-02-22 14:37:55,123 | INFO     | main | Tools registered: ['get_current_time', 'search_web']
2026-02-22 14:37:55,124 | INFO     | main | Agents registered: ['general']
2026-02-22 14:37:55,456 | INFO     | agent.general | Request start | agent=general | input_len=18
2026-02-22 14:37:55,457 | DEBUG    | agent.general | Iteration 1 | message_count=1
2026-02-22 14:37:55,789 | INFO     | agent.general | Tools called: ['get_current_time']
2026-02-22 14:37:55,790 | DEBUG    | agent.general | Tool result | get_current_time: 2026-02-22 14:37:55
2026-02-22 14:37:55,901 | INFO     | agent.general | Request end | agent=general | iterations=2
```

The `logger.name` field reflects the Python module hierarchy (e.g. `tools.registry`, `agents.registry`) or the custom name `agent.<agent_id>` for agent loggers.

---

## Handlers

### Console Handler

Always active. Writes to `stdout`. Useful during development and in containerised environments where stdout is captured by a log aggregator.

### File Handler (optional)

Added when `log_to_file=True`. Uses `TimedRotatingFileHandler`:

| Setting | Value |
|---------|-------|
| File path | `backend/logs/agent.log` |
| Rotation schedule | Daily at midnight |
| Files retained | 7 (older files are deleted automatically) |
| Archive suffix | `agent.log.YYYY-MM-DD` |
| Encoding | UTF-8 |

The `logs/` directory is created automatically if it does not exist. It is listed in `.gitignore` so log files are never committed.

### Hot-Reload Safety

uvicorn restarts the application module on file changes when running with `--reload`. Each restart would normally duplicate log handlers (adding a new one on top of the old ones). `setup_logging()` prevents this by clearing all existing handlers from the root logger before attaching new ones:

```python
root_logger.handlers.clear()
```

---

## Logger Names

Each module obtains its logger with `logging.getLogger(__name__)`:

| Module | Logger name |
|--------|------------|
| `main.py` | `main` |
| `config.py` | `config` |
| `agents/base.py` | `agents.base` |
| `agents/registry.py` | `agents.registry` |
| `agents/general_agent.py` | `agents.general_agent` |
| `tools/registry.py` | `tools.registry` |

Agent loggers use a custom name for easier filtering:

```python
# In BaseAgent.__init__():
self.logger = logging.getLogger(f"agent.{config.agent_id}")
# → "agent.general" for the GeneralAgent
```

This means you can filter log output to a specific agent with:
```bash
grep "agent.general" backend/logs/agent.log
```

---

## What Gets Logged

| Event | Level | Logger |
|-------|-------|--------|
| Tools registered at startup | `INFO` | `main` |
| Agents registered at startup | `INFO` | `main` |
| Request received | `INFO` | `agent.<id>` |
| Each loop iteration (count + message count) | `DEBUG` | `agent.<id>` |
| Tool names called per iteration | `INFO` | `agent.<id>` |
| Tool arguments | `DEBUG` | `agent.<id>` |
| Tool result (truncated to 300 chars) | `DEBUG` | `agent.<id>` |
| Request completed (iteration count) | `INFO` | `agent.<id>` |
| Tool registered | `DEBUG` | `tools.registry` |
| Agent registered | `DEBUG` | `agents.registry` |
| Unknown agent ID requested | `WARNING` | `agents.registry` |
| Agent execution error (with traceback) | `ERROR` | `main` |

---

## Controlling Log Verbosity

Set `LOG_LEVEL` in the environment or `.env` file:

```bash
# Development — see everything including tool args and results
export LOG_LEVEL=DEBUG

# Staging — see request start/end and tool calls, hide tool args
export LOG_LEVEL=INFO

# Production — see only warnings and errors
export LOG_LEVEL=WARNING
```

To disable file logging:

```bash
export LOG_TO_FILE=false
```
