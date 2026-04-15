from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NOTEBOOK_EXPORT_DIR = DATA_DIR / "notebook_exports"
SUMMARY_DIR = NOTEBOOK_EXPORT_DIR / "summaries"
FIGURE_DIR = NOTEBOOK_EXPORT_DIR / "figures"
TIMESERIES_EXPORT_PATH = DATA_DIR / "timeseries_export.csv"
RESERVOIR_PARAMETER_PATH = DATA_DIR / "reservoir_parameters.csv"
STORAGE_CURVE_PATH = DATA_DIR / "storage_V.csv"
OBSERVED_EVENT_PATH = DATA_DIR / "DD_sub1234_2025_hourlyPS.xlsx"


@dataclass
class DashboardBundle:
    summary_path: Path
    summary: dict[str, Any]
    observed: pd.DataFrame
    optimized: pd.DataFrame
    merged: pd.DataFrame
    parameters: dict[str, Any]
    readiness: dict[str, tuple[bool, str]]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_local_artifact(path_str: str | None, summary_path: Path, artifact_type: str) -> Path | None:
    if not path_str:
        return None

    candidate = Path(path_str)
    if candidate.exists():
        return candidate

    name = candidate.name
    if artifact_type == "summary_xlsx":
        fallback = summary_path.with_suffix(".xlsx")
        if fallback.exists():
            return fallback
    elif artifact_type == "figure_png":
        fallback = summary_path.parent.parent / "figures" / name
        if fallback.exists():
            return fallback
    elif artifact_type == "raw_event_source":
        fallback = OBSERVED_EVENT_PATH
        if fallback.exists():
            return fallback

    return candidate


def list_run_summaries() -> list[Path]:
    summaries = sorted(SUMMARY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return summaries


def load_reservoir_parameters(path: Path = RESERVOIR_PARAMETER_PATH) -> dict[str, Any]:
    df = pd.read_csv(path)
    values: dict[str, Any] = {}
    units: dict[str, Any] = {}
    for _, row in df.iterrows():
        key = str(row["parameter"]).strip().lower().replace(" ", "_").replace("-", "_")
        values[key] = row["values"]
        units[key] = row.get("unit")

    for key in (
        "normal_water_level",
        "pre_flood_target_level",
        "dead_water_level",
        "maximum_allowable_reservoir_level",
        "downstream_flow_threshold",
    ):
        if key in values:
            values[key] = float(pd.to_numeric(values[key], errors="coerce"))

    return {"values": values, "units": units}


def load_storage_curve(path: Path = STORAGE_CURVE_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[["storage_V", "storage_H"]].dropna().sort_values("storage_V")


def load_optimized_timeseries(path: Path = TIMESERIES_EXPORT_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    curve = load_storage_curve()
    df["reservoir_level_optimized"] = np.interp(df["V_Reservoir1"], curve["storage_V"], curve["storage_H"])
    return df


def load_observed_event(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df[df["Datetime"].notna()].sort_values("Datetime").infer_objects(copy=False).interpolate()
    return df


def build_merged_timeseries(summary: dict[str, Any], observed: pd.DataFrame, optimized: pd.DataFrame) -> pd.DataFrame:
    start_dt = pd.to_datetime(summary["time_window"]["start"])
    stop_dt = pd.to_datetime(summary["time_window"]["stop"])

    observed = observed[(observed["Datetime"] >= start_dt) & (observed["Datetime"] <= stop_dt)].copy()
    optimized = optimized[(optimized["time"] >= start_dt) & (optimized["time"] <= stop_dt)].copy()

    merged = observed.merge(optimized, left_on="Datetime", right_on="time", how="inner")
    merged["downstream_threshold"] = summary.get("reservoir_parameters", {}).get("values", {}).get("downstream_flow_threshold")
    merged["normal_water_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("normal_water_level")
    merged["pre_flood_target_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("pre_flood_target_level")
    merged["dead_water_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("dead_water_level")
    merged["maximum_allowable_reservoir_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("maximum_allowable_reservoir_level")
    return merged


def build_readiness(summary_path: Path, summary: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    raw_source = resolve_local_artifact(summary.get("raw_event_source"), summary_path, "raw_event_source")
    summary_xlsx = resolve_local_artifact(summary.get("files", {}).get("summary_xlsx"), summary_path, "summary_xlsx")
    figure_png = resolve_local_artifact(summary.get("files", {}).get("figure_png"), summary_path, "figure_png")
    return {
        "run_summary_json": (summary_path.exists(), str(summary_path)),
        "timeseries_export_csv": (TIMESERIES_EXPORT_PATH.exists(), str(TIMESERIES_EXPORT_PATH)),
        "reservoir_parameters_csv": (RESERVOIR_PARAMETER_PATH.exists(), str(RESERVOIR_PARAMETER_PATH)),
        "raw_event_source_xlsx": (raw_source.exists() if raw_source else False, str(raw_source) if raw_source else "missing"),
        "summary_xlsx": (summary_xlsx.exists() if summary_xlsx else False, str(summary_xlsx) if summary_xlsx else "missing"),
        "figure_png": (figure_png.exists() if figure_png else False, str(figure_png) if figure_png else "missing"),
    }


def load_dashboard_bundle(summary_path: Path) -> DashboardBundle:
    summary = load_json(summary_path)
    if "reservoir_parameters" not in summary:
        summary["reservoir_parameters"] = load_reservoir_parameters()

    raw_event_path = resolve_local_artifact(summary.get("raw_event_source"), summary_path, "raw_event_source")
    observed = load_observed_event(raw_event_path)
    optimized = load_optimized_timeseries()
    merged = build_merged_timeseries(summary, observed, optimized)
    readiness = build_readiness(summary_path, summary)

    return DashboardBundle(
        summary_path=summary_path,
        summary=summary,
        observed=observed,
        optimized=optimized,
        merged=merged,
        parameters=summary["reservoir_parameters"],
        readiness=readiness,
    )


def horizon_slice(df: pd.DataFrame, current_time: pd.Timestamp, horizon_hours: int) -> pd.DataFrame:
    end_time = current_time + pd.Timedelta(hours=horizon_hours)
    return df[(df["Datetime"] >= current_time) & (df["Datetime"] <= end_time)].copy()


def timestamp_options(df: pd.DataFrame) -> list[pd.Timestamp]:
    return list(pd.to_datetime(df["Datetime"]).tolist())


def recommendation_text(summary: dict[str, Any], current_row: pd.Series) -> tuple[str, str, str]:
    status = summary.get("status", "watch")
    params = summary["reservoir_parameters"]["values"]
    priority = params.get("priority_order_of_objectives", "")

    if status == "critical":
        action = "Vận hành theo chế độ phòng chống lũ và ưu tiên giám sát rủi ro hạ du."
        reason = (
            f"Lưu lượng hạ du theo phương án tối ưu vẫn vượt ngưỡng "
            f"{params.get('downstream_flow_threshold')} {summary['reservoir_parameters']['units'].get('downstream_flow_threshold', '')}."
        )
    elif status == "watch":
        action = "Duy trì xả điều tiết có kiểm soát và đánh giá sát cửa sổ dự báo tiếp theo."
        reason = "Quỹ đạo vận hành tối ưu đang tiệm cận các ngưỡng điều hành và cần được theo dõi chặt chẽ."
    else:
        action = "Tiếp tục phương án xả tối ưu và theo dõi các thay đổi của dự báo."
        reason = "Các chỉ số của hồ chứa và hạ du vẫn nằm trong các ngưỡng cấu hình của phương án tối ưu."

    tradeoff = (
        f"Đỉnh lưu lượng hạ du theo phương án tối ưu thấp hơn {summary['control_point']['flow_peak_reduction_percent']:.1f}% so với quan trắc, "
        f"đồng thời dung tích hồ cuối sự kiện thay đổi {summary['reservoir']['storage_change_percent']:.1f}%."
    )

    if isinstance(current_row, pd.Series) and not current_row.empty:
        reason += (
            f" Tại thời điểm đang xem, mực nước hồ là {current_row['WLDD']:.2f} m, "
            f"lưu lượng xả tối ưu là {current_row['Qoutput_Reservoir1']:.2f} m3/s, "
            f"và lưu lượng hạ du tối ưu là {current_row['Q_controlpoint']:.2f} m3/s."
        )

    if priority:
        tradeoff += f" Thứ tự ưu tiên mục tiêu: {priority}"

    return action, reason, tradeoff
