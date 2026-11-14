import json

import streamlit as st
import plotly.express as px

from utils.api_checker import check_api
from utils.data_handler import (
    add_history_record, calculate_statistics, history_to_dataframe,
    prepare_csv, response_time_dataframe,
)


DEMO_URLS = {
    "Custom URL": "",
    "JSONPlaceholder - Post": "https://jsonplaceholder.typicode.com/posts/1",
    "JSONPlaceholder - User": "https://jsonplaceholder.typicode.com/users/1",
    "HTTPBin - Success": "https://httpbin.org/status/200",
    "HTTPBin - Not Found": "https://httpbin.org/status/404",
    "HTTPBin - Server Error": "https://httpbin.org/status/500",
    "GitHub User": "https://api.github.com/users/octocat",
    "GitHub Repository": "https://api.github.com/repos/octocat/Hello-World",
    "Lucknow Weather": "https://api.open-meteo.com/v1/forecast?latitude=26.85&longitude=80.95&current=temperature_2m",
    "Kraken Market Data": "https://api.kraken.com/0/public/PreTrade?symbol=BTC%2FUSD",
}


def select_demo():
    url = DEMO_URLS[st.session_state.demo_api]
    if url:
        st.session_state.api_url = url


def display_result(result):
    status_code = result["status_code"]
    response_time = result["response_time_ms"]
    error = result["error"]

    if status_code is not None:
        api_status = "Healthy" if result["success"] else "HTTP Error"
    elif response_time is None:
        api_status = "Invalid URL"
    elif error and "timed out" in error.lower():
        api_status = "Timeout"
    else:
        api_status = "Connection Error"

    st.subheader("API Result")
    status_column, time_column, health_column = st.columns(3)
    status_column.metric("HTTP Status", status_code if status_code is not None else "N/A")
    time_column.metric("Response Time", f"{response_time:.2f} ms" if response_time is not None else "N/A")
    health_column.metric("API Status", api_status)

    st.caption("Response time is elapsed request-processing time, including reading the bounded body; it is not exact network-only latency.")

    if result["success"]:
        st.success("API is responding successfully.")
        if error:
            st.warning(error)
    elif status_code is not None:
        if 300 <= status_code < 400:
            st.warning(f"API returned HTTP {status_code}. Redirect was not followed.")
        else:
            st.error(f"API returned HTTP {status_code}.")
    elif api_status == "Invalid URL":
        st.warning(error)
    else:
        st.error(error)

    with st.expander("Response Details", expanded=True):
        st.write("Requested URL:")
        st.text(result["url"])
        st.write("Content type:")
        st.text(result["content_type"] or "N/A")
        st.write("Response preview:")
        preview = result["preview"]
        if preview:
            try:
                json.loads(preview)
            except ValueError:
                st.code(preview, language="text")
            else:
                st.json(preview)
        else:
            st.text("No response preview available.")
        if error:
            st.write("Error message:")
            st.text(error)


def clear_history():
    st.session_state.history = []
    st.session_state.history_cleared = True


def main():
    st.set_page_config(page_title="PingJasoos", page_icon="🔎", layout="centered")

    if "history" not in st.session_state:
        st.session_state.history = []

    st.title("PingJasoos")
    st.caption("Jahan API ka response ruk jaaye, wahan PingJasoos sach saamne laaye.")
    st.write("API Health & Performance Monitor")
    st.write(
        "A Python-based Streamlit application for checking API availability, "
        "HTTP status codes, and response times."
    )

    st.header("Check an API")
    st.write("Choose a demo API or enter a supported URL, then click Check API.")
    st.selectbox("Demo API", list(DEMO_URLS), key="demo_api", on_change=select_demo)
    url = st.text_input(
        "Enter API URL",
        placeholder="https://jsonplaceholder.typicode.com/posts/1",
        key="api_url",
    )
    if st.button("Check API", type="primary"):
        with st.spinner("Checking API..."):
            st.session_state.latest_result = check_api(url)
            add_history_record(st.session_state.history, st.session_state.latest_result)

    if "latest_result" in st.session_state:
        display_result(st.session_state.latest_result)
    else:
        st.info("Enter an API URL and click Check API to view its status.")

    st.subheader("Quick API Checks")
    selected = st.multiselect(
        "Demo endpoints", list(DEMO_URLS)[1:], max_selections=5, key="quick_apis",
    )
    if st.button("Check Selected APIs", disabled=not selected, key="check_selected"):
        batch_history = []
        with st.spinner("Checking selected APIs..."):
            for label in selected:
                result = check_api(DEMO_URLS[label])
                add_history_record(st.session_state.history, result)
                add_history_record(batch_history, result)
        st.dataframe(
            history_to_dataframe(batch_history).drop(columns="Error"), hide_index=True,
        )

    st.subheader("Investigation Summary")
    statistics = calculate_statistics(st.session_state.history)
    columns = st.columns(4)
    columns[0].metric("Total Checks", statistics["total"])
    columns[1].metric("Successful Checks", statistics["successful"])
    columns[2].metric("Failed Checks", statistics["failed"])
    average = statistics["average_response_time_ms"]
    columns[3].metric("Average Response Time", f"{average:.2f} ms" if average is not None else "N/A")
    st.caption("Average and chart include measured HTTP responses only, including HTTP errors; network failures and invalid URLs are excluded.")

    latency_data = response_time_dataframe(st.session_state.history)
    if latency_data.empty:
        st.subheader("API Response Time")
        st.info("No response-time data available yet.")
    else:
        figure = px.line(
            latency_data, x="Timestamp", y="Response Time (ms)",
            title="API Response Time", markers=True,
        )
        figure.update_layout(xaxis_title="Check timestamp (UTC)")
        st.plotly_chart(figure, config={"displayModeBar": False})

    st.subheader("Investigation History")
    if st.session_state.history:
        st.dataframe(
            history_to_dataframe(st.session_state.history).drop(columns="Error"),
            hide_index=True,
        )
    else:
        st.info("No API checks recorded yet.")
    st.download_button(
        "Download History", prepare_csv(st.session_state.history),
        file_name="pingjasoos_history.csv", mime="text/csv",
        disabled=not st.session_state.history, key="download_history",
    )
    st.button("Clear History", on_click=clear_history, key="clear_history")
    if st.session_state.pop("history_cleared", False):
        st.success("History cleared. The latest API result is unchanged.")

    st.subheader("About")
    st.write(
        "PingJasoos checks supported public APIs on demand. It displays HTTP status "
        "and response time, helps identify API errors, and provides small response previews. "
        "Supported providers are JSONPlaceholder, HTTPBin, GitHub, Open-Meteo, and Kraken. "
        "GitHub, Open-Meteo, and Kraken are limited to approved public demo endpoints."
    )
    st.caption("Checks run only when you click a check button. The latest single result and up to 100 history records are kept in this session.")


if __name__ == "__main__":
    main()
