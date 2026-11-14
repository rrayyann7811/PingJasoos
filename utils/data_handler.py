"""Small, session-history transforms; no requests or disk storage."""

from datetime import datetime, timezone
from math import isfinite
from urllib.parse import urlsplit, urlunsplit

import pandas as pd


HISTORY_LIMIT = 100
COLUMNS = ["Timestamp", "API URL", "HTTP Status", "Response Time", "Result", "Error"]


def history_url(url):
    """Omit credentials, query parameters and fragments from stored URLs."""
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    except ValueError:
        return "Invalid URL"


def valid_response_time(value):
    return value is not None and isfinite(value) and value >= 0


def add_history_record(history, result):
    """Append concise metadata in place and retain the latest 100 checks."""
    status = result.get("status_code")
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": history_url(result["url"]),
        "status_code": status,
        "response_time_ms": result.get("response_time_ms"),
        "success": status is not None and 200 <= status < 300,
        "error": result.get("error"),
    })
    del history[:-HISTORY_LIMIT]


def history_to_dataframe(history):
    """Return display/export rows, newest first, with explicit missing values."""
    rows = []
    for record in reversed(history):
        status = record["status_code"]
        latency = record["response_time_ms"]
        rows.append([
            record["timestamp"], record["url"],
            str(status) if status is not None else "N/A",
            f"{latency:.2f} ms" if valid_response_time(latency) else "N/A",
            "Success" if record["success"] else (
                f"Failed (HTTP {status})" if status is not None else "Failed (no HTTP response)"
            ),
            record["error"] or "N/A",
        ])
    return pd.DataFrame(rows, columns=COLUMNS)


def response_time_dataframe(history):
    """Return chronological HTTP-response latencies for statistics and charts."""
    rows = [
        {"Timestamp": record["timestamp"], "Response Time (ms)": record["response_time_ms"]}
        for record in history
        if record["status_code"] is not None and valid_response_time(record["response_time_ms"])
    ]
    return pd.DataFrame(rows, columns=["Timestamp", "Response Time (ms)"])


def calculate_statistics(history):
    latencies = response_time_dataframe(history)
    successful = sum(record["success"] for record in history)
    return {
        "total": len(history),
        "successful": successful,
        "failed": len(history) - successful,
        "average_response_time_ms": None if latencies.empty else float((latencies["Response Time (ms)"] / len(latencies)).sum()),
    }


def prepare_csv(history):
    """Create CSV bytes in memory, neutralizing spreadsheet formulas."""
    dataframe = history_to_dataframe(history)
    for column in ["API URL", "Error"]:
        dataframe[column] = dataframe[column].map(
            lambda value: "'" + value if value.lstrip().startswith(("=", "+", "-", "@"))
            or value.startswith(("\t", "\r", "\n")) else value
        )
    return dataframe.to_csv(index=False).encode("utf-8")
