from __future__ import annotations

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
LIB_DIR = PROJECT_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from dashboard_data import (  # noqa: E402
    load_dashboard_bundle,
    list_run_summaries,
    recommendation_text,
    resolve_local_artifact,
    horizon_slice,
    timestamp_options,
)


st.set_page_config(
    page_title="Mô phỏng vận hành lũ Dakdrinh",
    page_icon="🌊",
    layout="wide",
)


def format_status(status: str) -> str:
    mapping = {
        "normal": "Bình thường",
        "watch": "Cảnh báo",
        "critical": "Nghiêm trọng",
    }
    return mapping.get(status, status.title())


def status_color(status: str) -> str:
    colors = {
        "normal": "#1b7f3b",
        "watch": "#c47a00",
        "critical": "#b42318",
    }
    return colors.get(status, "#344054")


def make_level_chart(df, params, current_time):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Datetime"], y=df["WLDD"], name="Mực nước quan trắc", line=dict(color="black", width=2)))
    fig.add_trace(
        go.Scatter(
            x=df["Datetime"],
            y=df["reservoir_level_optimized"],
            name="Mực nước tối ưu",
            line=dict(color="#d92d20", width=2.5, dash="dash"),
        )
    )
    band_lines = [
        ("Mực nước chết", params["dead_water_level"], "#6941c6"),
        ("Mực đón lũ", params["pre_flood_target_level"], "#16a34a"),
        ("Mực nước bình thường", params["normal_water_level"], "#2563eb"),
        ("Mực tối đa cho phép", params["maximum_allowable_reservoir_level"], "#b42318"),
    ]
    for name, value, color in band_lines:
        fig.add_hline(y=value, line_color=color, line_dash="dot", annotation_text=name, annotation_position="top left")

    fig.add_vline(x=current_time, line_color="#98a2b3", line_dash="dash")
    fig.update_layout(
        title="Diễn biến mực nước hồ chứa",
        margin=dict(l=20, r=20, t=60, b=20),
        legend=dict(orientation="h", y=1.08),
        xaxis_title="Thời gian",
        yaxis_title="Mực nước (m)",
        height=360,
    )
    return fig


def make_release_chart(df, current_time):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Datetime"], y=df["QinDD"], name="Lưu lượng đến quan trắc", line=dict(color="#2f9e44", width=2)))
    fig.add_trace(go.Scatter(x=df["Datetime"], y=df["QoutDD"], name="Lưu lượng xả quan trắc", line=dict(color="black", width=2, dash="dash")))
    fig.add_trace(
        go.Scatter(
            x=df["Datetime"],
            y=df["Qoutput_Reservoir1"],
            name="Lưu lượng xả tối ưu",
            line=dict(color="#d92d20", width=2.5),
        )
    )
    fig.add_vline(x=current_time, line_color="#98a2b3", line_dash="dash")
    fig.update_layout(
        title="Quá trình lưu lượng đến và xả hồ chứa",
        margin=dict(l=20, r=20, t=60, b=20),
        legend=dict(orientation="h", y=1.08),
        xaxis_title="Thời gian",
        yaxis_title="Lưu lượng (m3/s)",
        height=360,
    )
    return fig


def make_downstream_chart(df, threshold, current_time):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Datetime"], y=df["QinSG"], name="Lưu lượng hạ du quan trắc", line=dict(color="black", width=2)))
    fig.add_trace(
        go.Scatter(
            x=df["Datetime"],
            y=df["Q_controlpoint"],
            name="Lưu lượng hạ du tối ưu",
            line=dict(color="#7a5af8", width=2.5),
        )
    )
    if threshold is not None:
        fig.add_hline(
            y=threshold,
            line_color="#b42318",
            line_dash="dot",
            annotation_text="Ngưỡng hạ du",
            annotation_position="top left",
        )
    fig.add_vline(x=current_time, line_color="#98a2b3", line_dash="dash")
    fig.update_layout(
        title="Quá trình lưu lượng tại điểm kiểm soát hạ du",
        margin=dict(l=20, r=20, t=60, b=20),
        legend=dict(orientation="h", y=1.08),
        xaxis_title="Thời gian",
        yaxis_title="Lưu lượng (m3/s)",
        height=360,
    )
    return fig


def render_readiness(readiness: dict[str, tuple[bool, str]]):
    st.sidebar.subheader("Tình trạng tệp dữ liệu")
    for label, (ok, path_text) in readiness.items():
        icon = "Sẵn sàng" if ok else "Thiếu"
        st.sidebar.caption(f"{icon} {label}")
        st.sidebar.code(path_text, language=None)


def render_alerts(flags: dict[str, bool]):
    label_map = {
        "reservoir_above_pre_flood_target": "Mực nước hồ vượt mực đón lũ",
        "reservoir_above_normal_level": "Mực nước hồ vượt mực bình thường",
        "reservoir_above_maximum_allowable": "Mực nước hồ vượt mức tối đa cho phép",
        "downstream_above_threshold_optimized": "Lưu lượng hạ du tối ưu vượt ngưỡng",
        "downstream_above_threshold_observed": "Lưu lượng hạ du quan trắc vượt ngưỡng",
    }
    active = [label_map[key] for key, value in flags.items() if value]
    if not active:
        st.success("Không có cảnh báo ngưỡng nào đang kích hoạt trong lần chạy tối ưu đã chọn.")
    else:
        for item in active:
            st.warning(item)


def main():
    st.title("Mô phỏng vận hành lũ Dakdrinh")
    st.caption("Màn hình tua lại diễn biến lũ năm 2025 và khuyến nghị vận hành dựa trên kết quả tối ưu hóa được tạo từ notebook.")

    summary_paths = list_run_summaries()
    if not summary_paths:
        st.error("Không tìm thấy tệp tổng hợp JSON trong output/notebook_exports/summaries. Hãy chạy notebook trước.")
        st.stop()

    summary_options = {path.name: path for path in summary_paths}
    selected_summary_name = st.sidebar.selectbox("Bản tổng hợp lần chạy", list(summary_options.keys()))
    try:
        bundle = load_dashboard_bundle(summary_options[selected_summary_name])
    except Exception as exc:
        st.error(f"Không thể tải dữ liệu bảng điều khiển: {exc}")
        st.info("Cần bảo đảm các tệp đầu ra từ notebook là bản mới nhất và môi trường đã cài `openpyxl`.")
        st.stop()

    render_readiness(bundle.readiness)

    horizons = bundle.summary.get("dashboard_defaults", {}).get("horizons_hours", [24, 48, 72])
    default_horizon = bundle.summary.get("dashboard_defaults", {}).get("default_horizon_hours", 48)
    selected_horizon = st.sidebar.radio("Tầm nhìn điều hành", horizons, index=horizons.index(default_horizon) if default_horizon in horizons else 0)

    timestamps = timestamp_options(bundle.merged)
    if not timestamps:
        st.error("Không tìm thấy mốc thời gian đồng bộ giữa dữ liệu quan trắc và dữ liệu tối ưu cho lần chạy đã chọn.")
        st.stop()

    default_time = timestamps[0]
    current_time = st.sidebar.select_slider("Thời điểm tua lại", options=timestamps, value=default_time)

    window_df = horizon_slice(bundle.merged, current_time, selected_horizon)
    if window_df.empty:
        st.error("Khung thời gian đã chọn không có dữ liệu.")
        st.stop()
    current_row = window_df.iloc[0]

    status = bundle.summary.get("status", "watch")
    st.markdown(
        f"""
        <div style="padding:0.8rem 1rem;border-radius:12px;background:{status_color(status)};color:white;font-weight:600;display:inline-block;">
            Trạng thái: {format_status(status)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    top1, top2, top3, top4, top5 = st.columns(5)
    top1.metric("Thời điểm", current_time.strftime("%Y-%m-%d %H:%M"))
    top2.metric("Mực nước hồ", f"{current_row['WLDD']:.2f} m")
    top3.metric("Lưu lượng xả tối ưu", f"{current_row['Qoutput_Reservoir1']:.2f} m3/s")
    top4.metric("Lưu lượng hạ du tối ưu", f"{current_row['Q_controlpoint']:.2f} m3/s")
    top5.metric("Mực nước cuối kỳ (tối ưu)", f"{bundle.summary['reservoir']['water_level_optimized_end_m']:.2f} m")

    left, right = st.columns([1.1, 0.9])
    with left:
        st.subheader("Cảnh báo")
        render_alerts(bundle.summary.get("threshold_flags", {}))
    with right:
        st.subheader("Khuyến nghị")
        action, reason, tradeoff = recommendation_text(bundle.summary, current_row)
        st.info(action)
        st.write(reason)
        st.caption(tradeoff)

    chart1, chart2 = st.columns(2)
    params = bundle.parameters["values"]
    with chart1:
        st.plotly_chart(make_level_chart(window_df, params, current_time), use_container_width=True)
    with chart2:
        st.plotly_chart(make_release_chart(window_df, current_time), use_container_width=True)

    st.plotly_chart(
        make_downstream_chart(window_df, params.get("downstream_flow_threshold"), current_time),
        use_container_width=True,
    )

    st.subheader("Tổng hợp lần chạy")
    sum1, sum2, sum3, sum4 = st.columns(4)
    sum1.metric("Đỉnh xả quan trắc", f"{bundle.summary['reservoir']['release_peak_observed']['value']:.1f} m3/s")
    sum2.metric("Đỉnh xả tối ưu", f"{bundle.summary['reservoir']['release_peak_optimized']['value']:.1f} m3/s")
    sum3.metric("Đỉnh hạ du quan trắc", f"{bundle.summary['control_point']['flow_peak_observed']['value']:.1f} m3/s")
    sum4.metric("Đỉnh hạ du tối ưu", f"{bundle.summary['control_point']['flow_peak_optimized']['value']:.1f} m3/s")

    st.dataframe(
        {
            "Chỉ số": [
                "Nhãn sự kiện",
                "Thời điểm tạo lần chạy",
                "Mực nước cuối kỳ quan trắc",
                "Mực nước cuối kỳ tối ưu",
                "Mức giảm đỉnh lưu lượng xả",
                "Mức giảm đỉnh lưu lượng hạ du",
            ],
            "Giá trị": [
                bundle.summary["event_label"],
                bundle.summary.get("run_generated_at", "n/a"),
                f"{bundle.summary['reservoir']['water_level_observed_end_m']:.2f} m",
                f"{bundle.summary['reservoir']['water_level_optimized_end_m']:.2f} m",
                f"{bundle.summary['reservoir']['release_peak_reduction_percent']:.1f} %",
                f"{bundle.summary['control_point']['flow_peak_reduction_percent']:.1f} %",
            ],
        },
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Tệp đầu ra báo cáo")
    files = bundle.summary.get("files", {})
    col_a, col_b, col_c = st.columns(3)
    json_bytes = bundle.summary_path.read_bytes()
    xlsx_path = resolve_local_artifact(files.get("summary_xlsx"), bundle.summary_path, "summary_xlsx")
    png_path = resolve_local_artifact(files.get("figure_png"), bundle.summary_path, "figure_png")
    with col_a:
        st.download_button("Tải bản tổng hợp JSON", data=json_bytes, file_name=bundle.summary_path.name, mime="application/json")
        st.code(str(bundle.summary_path), language=None)
    with col_b:
        if xlsx_path and xlsx_path.exists():
            st.download_button("Tải bản tổng hợp XLSX", data=xlsx_path.read_bytes(), file_name=xlsx_path.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.code(str(xlsx_path), language=None)
        else:
            st.error("Không tìm thấy tệp tổng hợp XLSX.")
    with col_c:
        if png_path and png_path.exists():
            st.download_button("Tải hình PNG", data=png_path.read_bytes(), file_name=png_path.name, mime="image/png")
            st.code(str(png_path), language=None)
        else:
            st.error("Không tìm thấy tệp hình PNG.")


if __name__ == "__main__":
    main()
