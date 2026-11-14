from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import DEMO_URLS


def streamed_response(**kwargs):
    response = Mock(encoding="utf-8", **kwargs)
    if "text" not in kwargs:
        response.text = '{"id": 1, "title": "Hello"}'
    response.iter_content.side_effect = lambda chunk_size: iter([response.text.encode("utf-8")])
    return response


@pytest.fixture
def app():
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()


def test_initial_page_and_no_automatic_checks(app):
    with patch("utils.api_checker.requests.get") as get:
        app.text_input[0].set_value("https://httpbin.org/get").run()
        app.selectbox[0].select("HTTPBin - Success").run()
    get.assert_not_called()
    assert not app.exception
    assert app.title[0].value == "PingJasoos"
    assert app.caption[0].value == "Jahan API ka response ruk jaaye, wahan PingJasoos sach saamne laaye."
    assert [metric.value for metric in app.metric] == ["0", "0", "0", "N/A"]


@pytest.mark.parametrize("label, url", list(DEMO_URLS.items())[1:])
def test_demo_selection_and_manual_editing(app, label, url):
    app.selectbox[0].select(label).run()
    assert app.text_input[0].value == url
    app.text_input[0].set_value("https://httpbin.org/get").run()
    assert app.text_input[0].value == "https://httpbin.org/get"
    app.selectbox[0].select("Custom URL").run()
    assert app.text_input[0].value == "https://httpbin.org/get"
    assert not app.exception


@pytest.mark.parametrize("label", [
    "GitHub User", "GitHub Repository", "Lucknow Weather", "Kraken Market Data",
])
def test_new_demo_check_updates_result_and_history(app, label):
    response = streamed_response(status_code=200, headers={"Content-Type": "application/json"})
    app.selectbox[0].select(label).run()
    with patch("utils.api_checker.requests.get", return_value=response) as get:
        app.button[0].click().run()
    get.assert_called_once_with(DEMO_URLS[label], timeout=5, allow_redirects=False, stream=True)
    assert not app.exception
    assert app.metric[0].value == "200"
    assert len(app.session_state.history) == 1
    assert len(app.json) == 1


@pytest.mark.parametrize("status", [200, 404, 500, 302])
def test_button_http_results_and_persistence(app, status):
    response = streamed_response(status_code=status, headers={"Content-Type": "application/json"})
    app.selectbox[0].select("JSONPlaceholder - Post").run()
    with patch("utils.api_checker.requests.get", return_value=response) as get:
        app.button[0].click().run()
        get.assert_called_once_with(DEMO_URLS["JSONPlaceholder - Post"], timeout=5, allow_redirects=False, stream=True)
        assert not app.exception
        assert app.metric[0].value == str(status)
        assert app.metric[1].value.endswith(" ms")
        assert app.metric[2].value == ("Healthy" if status == 200 else "HTTP Error")
        assert len(app.json) == 1
        if status == 200:
            assert app.success
        elif status == 302:
            assert "not followed" in app.warning[0].value
        else:
            assert str(status) in app.error[0].value
        result = app.session_state.latest_result.copy()
        app.selectbox[0].select("HTTPBin - Not Found").run()
        app.text_input[0].set_value("invalid").run()
        assert app.session_state.latest_result == result
        assert app.metric[0].value == str(status)
        assert get.call_count == 1


@pytest.mark.parametrize("url", ["", "invalid", "http://localhost:8000", "https://example.com"])
def test_invalid_urls(app, url):
    app.text_input[0].set_value(url).run()
    with patch("utils.api_checker.requests.get") as get:
        app.button[0].click().run()
    get.assert_not_called()
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == ["N/A", "N/A", "Invalid URL"]
    assert app.warning


@pytest.mark.parametrize("exception, status", [
    (requests.Timeout(), "Timeout"),
    (requests.ConnectionError(), "Connection Error"),
    (requests.RequestException(), "Connection Error"),
])
def test_network_failures(app, exception, status):
    app.selectbox[0].select("HTTPBin - Success").run()
    with patch("utils.api_checker.requests.get", side_effect=exception):
        app.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "N/A"
    assert app.metric[2].value == status
    assert app.error


@pytest.mark.parametrize("preview", ['{"text": "truncated', "plain text", ""])
def test_non_json_and_empty_previews(app, preview):
    result = {
        "url": "https://httpbin.org/get", "status_code": 200,
        "response_time_ms": 0.0, "success": True,
        "content_type": "application/json", "preview": preview,
        "error": "Response declared JSON but could not be parsed." if preview else None,
    }
    with patch("utils.api_checker.check_api", return_value=result) as checker:
        app.button[0].click().run()
    checker.assert_called_once()
    assert not app.exception
    assert not app.json
    assert app.metric[1].value == "0.00 ms"
    if preview:
        assert app.code[0].value == preview
        assert app.warning
    else:
        assert any(text.value == "No response preview available." for text in app.text)


def test_history_reruns_chart_download_and_clear(app):
    assert any(info.value == "No response-time data available yet." for info in app.info)
    assert app.get("download_button")[0].proto.disabled
    response = streamed_response(status_code=404, headers={"Content-Type": "text/plain"}, text="missing")
    app.selectbox[0].select("HTTPBin - Not Found").run()
    with patch("utils.api_checker.requests.get", return_value=response) as get:
        app.button[0].click().run()
        assert len(app.session_state.history) == 1
        assert app.get("plotly_chart")
        assert not app.get("download_button")[0].proto.disabled
        app.text_input[0].set_value("invalid").run()
        assert len(app.session_state.history) == 1
        latest = app.session_state.latest_result.copy()
        app.button(key="clear_history").click().run()
        assert app.session_state.history == []
        assert app.session_state.latest_result == latest
        assert [metric.value for metric in app.metric[-4:]] == ["0", "0", "0", "N/A"]
        assert not app.get("plotly_chart")
        assert not app.dataframe
        assert app.get("download_button")[0].proto.disabled
        assert any(message.value == "History cleared. The latest API result is unchanged." for message in app.success)
        assert get.call_count == 1
    assert not app.exception


def test_multiple_checks_are_explicit_and_sequential(app):
    labels = list(DEMO_URLS)[1:6]
    responses = [streamed_response(status_code=status, headers={"Content-Type": "text/plain"}, text="result")
                 for status in [200, 200, 200, 404, 500]]
    with patch("utils.api_checker.requests.get", side_effect=responses) as get:
        app.multiselect[0].set_value(labels).run()
        get.assert_not_called()
        app.button(key="check_selected").click().run()
        assert [call.args[0] for call in get.call_args_list] == [DEMO_URLS[label] for label in labels]
        assert len(app.session_state.history) == 5
        assert [metric.value for metric in app.metric[:3]] == ["5", "3", "2"]
        assert len(app.dataframe) == 2
        assert len(app.dataframe[0].value) == 5
        app.run()
        assert get.call_count == 5
        assert len(app.session_state.history) == 5
    assert not app.exception


def test_batch_continues_after_network_failure(app):
    assert app.button(key="check_selected").disabled
    labels = list(DEMO_URLS)[1:4]
    response = streamed_response(status_code=200, headers={"Content-Type": "text/plain"}, text="ok")
    with patch("utils.api_checker.requests.get", side_effect=[requests.Timeout("private"), response, response]) as get:
        app.multiselect[0].set_value(labels).run()
        app.button(key="check_selected").click().run()
        assert get.call_count == 3
        assert len(app.session_state.history) == 3
        assert [metric.value for metric in app.metric[:3]] == ["3", "2", "1"]
        assert len(app.dataframe[0].value) == 3
        assert "private" not in app.dataframe[0].value.to_string()
        assert len(app.get("plotly_chart")) == 1
        app.multiselect[0].set_value([]).run()
        assert get.call_count == 3
        assert app.button(key="check_selected").disabled
    assert not app.exception
