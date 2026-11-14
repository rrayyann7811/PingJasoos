from unittest.mock import Mock, patch

import pytest
import requests

from utils.api_checker import PREVIEW_LIMIT, check_api, validate_url


URL = "https://jsonplaceholder.typicode.com/posts/1"
RESULT_KEYS = {"url", "status_code", "response_time_ms", "success", "content_type", "preview", "error"}


def streamed_response(**kwargs):
    response = Mock(encoding="utf-8", **kwargs)
    if "text" not in kwargs:
        response.text = '{"id": 1, "title": "Hello"}'
    response.iter_content.side_effect = lambda chunk_size: iter([response.text.encode("utf-8")])
    return response


@pytest.mark.parametrize("url", [URL, "https://jsonplaceholder.typicode.com/users/1", "https://httpbin.org/status/404", "http://httpbin.org/get", "https://httpbin.org:443/get"])
def test_approved_urls(url):
    assert validate_url(url) is None


@pytest.mark.parametrize("url", [
    "", "   ", None, "not-a-url", "ftp://httpbin.org/get", "https://",
    "https://httpbin.org:bad/get", "https://[broken", "https://httpbin.org:8000/get",
    "https://user:password@httpbin.org/get", "https://@httpbin.org/get",
    "http://localhost:8000", "http://127.0.0.1:8501", "http://192.168.1.1",
    "http://10.0.0.1", "http://172.16.0.1", "http://169.254.169.254",
    "http://[::1]", "http://internal", "https://example.com",
    "https://httpbin.org.example.com", "https://fakehttpbin.org",
    "https://jsonplaceholder.typicode.com.evil.example/posts/1",
    "https://httpbin.org/get\n", "https://httpbin.org\\@example.com",
])
def test_rejected_urls_never_send_requests(url):
    with patch("utils.api_checker.requests.get") as get:
        result = check_api(url)
    get.assert_not_called()
    assert set(result) == RESULT_KEYS
    assert result["error"]
    assert result["success"] is False
    assert result["status_code"] is None
    assert result["response_time_ms"] is None


@pytest.fixture
def response():
    response = streamed_response(status_code=200, headers={"Content-Type": "application/json; charset=utf-8"})
    response.text = '{"id": 1, "title": "Hello"}'
    return response


def test_success_and_timing(response):
    with patch("utils.api_checker.requests.get", return_value=response) as get, patch(
        "utils.api_checker.time.perf_counter", side_effect=[10, 10.125]
    ):
        result = check_api(URL)
    get.assert_called_once_with(URL, timeout=5, allow_redirects=False, stream=True)
    assert set(result) == RESULT_KEYS
    assert result["url"] == URL
    assert result["status_code"] == 200
    assert result["success"] is True
    assert result["error"] is None
    assert result["response_time_ms"] == 125.0
    assert '"id": 1' in result["preview"]
    response.close.assert_called_once()


@pytest.mark.parametrize("status", [201, 204, 299, 301, 302, 307, 400, 404, 500, 503])
def test_http_statuses(response, status):
    response.status_code = status
    response.headers = {"Content-Type": "text/plain"}
    response.text = "Response"
    with patch("utils.api_checker.requests.get", return_value=response) as get:
        result = check_api(URL)
    assert result["status_code"] == status
    assert result["success"] == (200 <= status < 300)
    assert result["preview"] == "Response"
    assert result["response_time_ms"] >= 0
    if status >= 300:
        assert str(status) in result["error"]
    if 300 <= status < 400:
        assert "not followed" in result["error"]
    assert get.call_count == 1


@pytest.mark.parametrize("exception, message", [
    (requests.Timeout("internal detail"), "timed out"),
    (requests.ConnectionError("internal detail"), "connect"),
    (requests.RequestException("internal detail"), "could not be completed"),
])
def test_request_failures(exception, message):
    with patch("utils.api_checker.requests.get", side_effect=exception), patch(
        "utils.api_checker.time.perf_counter", side_effect=[1, 6]
    ):
        result = check_api(URL)
    assert set(result) == RESULT_KEYS
    assert result["success"] is False
    assert result["status_code"] is None
    assert result["response_time_ms"] == 5000.0
    assert message in result["error"]
    assert "internal detail" not in result["error"]


@pytest.mark.parametrize("status", [200, 500])
def test_invalid_json(response, status):
    response.status_code = status
    response.text = "invalid JSON"
    with patch("utils.api_checker.requests.get", return_value=response):
        result = check_api(URL)
    assert result["preview"] == "invalid JSON"
    assert "could not be parsed" in result["error"]
    assert result["success"] == (status == 200)
    if status == 500:
        assert "500" in result["error"]


@pytest.mark.parametrize("content_type", ["text/plain", "application/json", "application/problem+json"])
def test_preview_limit(response, content_type):
    response.headers = {"Content-Type": content_type}
    response.text = "x" * 1000
    with patch("utils.api_checker.requests.get", return_value=response):
        result = check_api(URL)
    assert len(result["preview"]) == PREVIEW_LIMIT
    if content_type != "text/plain":
        response.iter_content.assert_called_once()


@pytest.mark.parametrize("status", [200, 500])
def test_large_stream_is_bounded_and_closed(status):
    from utils.api_checker import MAX_RESPONSE_BYTES, READ_CHUNK_BYTES

    response = streamed_response(status_code=status, headers={"Content-Type": "application/json"})
    consumed = []

    def chunks(chunk_size):
        assert chunk_size == READ_CHUNK_BYTES
        for index in range(MAX_RESPONSE_BYTES // chunk_size + 10):
            consumed.append(index)
            yield b"x" * chunk_size

    response.iter_content.side_effect = chunks
    with patch("utils.api_checker.requests.get", return_value=response):
        result = check_api(URL)
    assert len(consumed) == MAX_RESPONSE_BYTES // READ_CHUNK_BYTES + 1
    assert "1 MiB" in result["error"]
    assert result["status_code"] == status
    assert result["success"] == (status == 200)
    assert len(result["preview"]) == PREVIEW_LIMIT
    response.close.assert_called_once()
    response.json.assert_not_called()


@pytest.mark.parametrize("exception", [requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError])
def test_stream_read_failure_retains_status_time_and_closes(exception):
    response = streamed_response(status_code=404, headers={"Content-Type": "text/plain"})
    response.iter_content.side_effect = exception("private detail")
    with patch("utils.api_checker.requests.get", return_value=response), patch(
        "utils.api_checker.time.perf_counter", side_effect=[10, 10.123456]
    ):
        result = check_api(URL)
    assert result["status_code"] == 404
    assert result["success"] is False
    assert result["response_time_ms"] == 123.46
    assert "404" in result["error"]
    assert "private detail" not in result["error"]
    response.close.assert_called_once()


def test_exact_size_limit_and_unknown_encoding():
    from utils.api_checker import MAX_RESPONSE_BYTES

    response = streamed_response(status_code=200, headers={"Content-Type": "text/plain"}, text="x" * MAX_RESPONSE_BYTES)
    response.encoding = "unknown-encoding"
    with patch("utils.api_checker.requests.get", return_value=response):
        result = check_api(URL)
    assert result["error"] is None
    assert result["preview"] == "x" * PREVIEW_LIMIT
    response.close.assert_called_once()


def test_deep_json_does_not_crash():
    response = streamed_response(status_code=200, headers={"Content-Type": "application/json"}, text="[" * 2000 + "]" * 2000)
    with patch("utils.api_checker.requests.get", return_value=response):
        result = check_api(URL)
    assert result["success"]
    assert "could not be parsed" in result["error"]
    response.close.assert_called_once()
