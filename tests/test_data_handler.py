import io
from datetime import datetime

import pandas as pd
import pytest

from utils.data_handler import (
    add_history_record, calculate_statistics, history_to_dataframe,
    prepare_csv, response_time_dataframe,
)


def result(status=200, latency=100, url="https://httpbin.org/get", error=None):
    return dict(url=url, status_code=status, response_time_ms=latency,
                success=status == 200, error=error, preview="private body")


def test_record_metadata_and_privacy():
    history = []
    add_history_record(history, result(url="https://user:secret@httpbin.org/get?token=secret#secret"))
    assert history[0]["url"] == "https://httpbin.org/get"
    assert datetime.fromisoformat(history[0]["timestamp"]).utcoffset().total_seconds() == 0
    assert set(history[0]) == {"timestamp", "url", "status_code", "response_time_ms", "success", "error"}


def test_limit():
    history = []
    for index in range(105):
        add_history_record(history, result(latency=index))
    assert len(history) == 100
    assert history[0]["response_time_ms"] == 5
    assert history[-1]["response_time_ms"] == 104


@pytest.mark.parametrize("statuses, expected", [
    ([200, 201, 299], (3, 3, 0, 100)),
    ([404, 500, None], (3, 0, 3, 100)),
    ([200, 404, None], (3, 1, 2, 100)),
    ([], (0, 0, 0, None)),
    ([None], (1, 0, 1, None)),
])
def test_statistics(statuses, expected):
    history = []
    for status in statuses:
        add_history_record(history, result(status))
    assert tuple(calculate_statistics(history).values()) == expected


def test_missing_times_and_http_error_latency():
    history = []
    for status, latency in [(200, 0), (404, 200), (500, 400), (None, 5000), (200, None), (200, float("nan"))]:
        add_history_record(history, result(status, latency))
    assert calculate_statistics(history)["average_response_time_ms"] == 200
    assert response_time_dataframe(history)["Response Time (ms)"].tolist() == [0, 200, 400]
    assert "nan" not in history_to_dataframe(history).to_string().lower()


def test_dataframe_csv_and_clear():
    history = []
    add_history_record(history, result())
    add_history_record(history, result(None, None, "=1+1", "\t=evil()"))
    dataframe = history_to_dataframe(history)
    assert len(dataframe) == 2
    assert dataframe.iloc[0]["HTTP Status"] == "N/A"
    assert dataframe.iloc[0]["Response Time"] == "N/A"
    exported = pd.read_csv(io.BytesIO(prepare_csv(history)), keep_default_na=False)
    assert exported.iloc[0]["API URL"] == "'=1+1"
    assert exported.iloc[0]["Error"] == "'\t=evil()"
    assert exported.iloc[1].to_dict() == dataframe.iloc[1].to_dict()
    history.clear()
    assert history_to_dataframe(history).empty
    assert calculate_statistics(history)["total"] == 0
    assert response_time_dataframe(history).empty
    assert len(pd.read_csv(io.BytesIO(prepare_csv(history)))) == 0


@pytest.mark.parametrize("text", ["=SUM(1)", "+1", "-1", "@x", "  =1", "\rtest", "\ntest"])
def test_csv_formula_protection(text):
    history = []
    add_history_record(history, result(error=text))
    exported = pd.read_csv(io.BytesIO(prepare_csv(history)))
    assert exported.iloc[0]["Error"] == "'" + text


@pytest.mark.parametrize("latency", [float("inf"), float("-inf"), float("nan"), -1, None])
def test_unavailable_latencies_are_not_displayed_or_averaged(latency):
    history = []
    add_history_record(history, result(latency=latency))
    assert history_to_dataframe(history).iloc[0]["Response Time"] == "N/A"
    assert response_time_dataframe(history).empty
    assert calculate_statistics(history)["average_response_time_ms"] is None


def test_csv_unicode_order_privacy_and_count_identity():
    history = []
    for status in [200, 299, 302, 404, 500, None]:
        add_history_record(history, result(status, url="https://httpbin.org/get?api_key=secret#secret", error="जाँच"))
    dataframe = history_to_dataframe(history)
    exported = pd.read_csv(io.BytesIO(prepare_csv(history)), keep_default_na=False)
    pd.testing.assert_frame_equal(exported, dataframe)
    assert "secret" not in prepare_csv(history).decode("utf-8")
    assert "private body" not in prepare_csv(history).decode("utf-8")
    assert dataframe["Timestamp"].tolist() == [record["timestamp"] for record in reversed(history)]
    stats = calculate_statistics(history)
    assert stats["total"] == stats["successful"] + stats["failed"] == 6
    assert stats["successful"] == 2
