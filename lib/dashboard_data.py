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
DOWNSTREAM_WL_K = 71.41922
DOWNSTREAM_WL_P = 2.016432
DOWNSTREAM_WL_WREF = 27.2


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

    alias_map = {
        "pre_flood_target_level": "pre_flood_maximum_level",
        "pre_flood_maximum_level": "pre_flood_target_level",
    }
    for source_key, target_key in alias_map.items():
        if source_key in values and target_key not in values:
            values[target_key] = values[source_key]
            units[target_key] = units.get(source_key)

    for key in (
        "normal_water_level",
        "pre_flood_target_level",
        "pre_flood_maximum_level",
        "pre_flood_minimum_level",
        "dead_water_level",
        "maximum_allowable_reservoir_level",
        "downstream_flow_threshold",
        "downstream_water_level_threshold",
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
    for column in ("Qoutput_Reservoir1", "Q_controlpoint"):
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce").clip(lower=0.0)
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
    merged["pre_flood_maximum_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("pre_flood_maximum_level")
    merged["pre_flood_minimum_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("pre_flood_minimum_level")
    merged["dead_water_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("dead_water_level")
    merged["maximum_allowable_reservoir_level"] = summary.get("reservoir_parameters", {}).get("values", {}).get("maximum_allowable_reservoir_level")
    merged["downstream_water_level_threshold"] = summary.get("reservoir_parameters", {}).get("values", {}).get("downstream_water_level_threshold")
    merged["downstream_wl_optimized"] = np.power(merged["Q_controlpoint"] / DOWNSTREAM_WL_K, 1.0 / DOWNSTREAM_WL_P) + DOWNSTREAM_WL_WREF
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


def percent_change(baseline: float, candidate: float) -> float:
    if pd.isna(baseline) or baseline == 0:
        return 0.0
    return ((candidate - baseline) / baseline) * 100.0


def format_flow_comparison(label: str, change_percent: float) -> str:
    if abs(change_percent) < 0.05:
        return f"{label} tương đương quan trắc 0.0%"
    direction = "cao hơn" if change_percent > 0 else "thấp hơn"
    return f"{label} {direction} quan trắc {change_percent:.1f}%"


def derive_window_summary(window_df: pd.DataFrame) -> dict[str, Any]:
    if window_df.empty:
        return {}

    release_peak_observed = float(window_df["QoutDD"].max())
    release_peak_optimized = float(window_df["Qoutput_Reservoir1"].max())
    downstream_peak_observed = float(window_df["QinSG"].max())
    downstream_peak_optimized = float(window_df["Q_controlpoint"].max())

    observed_end_wl = float(window_df["WLDD"].iloc[-1])
    optimized_end_wl = float(window_df["reservoir_level_optimized"].iloc[-1])

    return {
        "window_start": window_df["Datetime"].min(),
        "window_end": window_df["Datetime"].max(),
        "release_peak_observed": release_peak_observed,
        "release_peak_optimized": release_peak_optimized,
        "downstream_peak_observed": downstream_peak_observed,
        "downstream_peak_optimized": downstream_peak_optimized,
        "release_peak_reduction_percent": percent_change(release_peak_observed, release_peak_optimized),
        "downstream_peak_reduction_percent": percent_change(downstream_peak_observed, downstream_peak_optimized),
        "water_level_observed_end_m": observed_end_wl,
        "water_level_optimized_end_m": optimized_end_wl,
    }


def derive_operational_state(window_df: pd.DataFrame, summary: dict[str, Any]) -> dict[str, Any]:
    params = summary["reservoir_parameters"]["values"]
    current_row = window_df.iloc[0] if not window_df.empty else pd.Series(dtype="object")

    pre_flood_target = params.get("pre_flood_target_level")
    normal_level = params.get("normal_water_level")
    maximum_level = params.get("maximum_allowable_reservoir_level")
    downstream_threshold = params.get("downstream_flow_threshold")

    def exceeds(series_name: str, threshold: float | None) -> bool:
        if threshold is None or series_name not in window_df:
            return False
        return bool((window_df[series_name] > threshold).fillna(False).any())

    threshold_flags = {
        "reservoir_above_pre_flood_target": exceeds("reservoir_level_optimized", pre_flood_target),
        "reservoir_above_normal_level": exceeds("reservoir_level_optimized", normal_level),
        "reservoir_above_maximum_allowable": exceeds("reservoir_level_optimized", maximum_level),
        "downstream_above_threshold_optimized": exceeds("Q_controlpoint", downstream_threshold),
    }

    if threshold_flags["reservoir_above_maximum_allowable"] or threshold_flags["downstream_above_threshold_optimized"]:
        status = "critical"
    elif threshold_flags["reservoir_above_pre_flood_target"] or threshold_flags["reservoir_above_normal_level"]:
        status = "watch"
    else:
        status = "normal"

    return {
        "status": status,
        "threshold_flags": threshold_flags,
        "current_row": current_row,
        "window_start": window_df["Datetime"].min() if "Datetime" in window_df else None,
        "window_end": window_df["Datetime"].max() if "Datetime" in window_df else None,
    }


def recommendation_text(
    summary: dict[str, Any],
    operational_state: dict[str, Any],
    window_summary: dict[str, Any],
) -> tuple[str, str, str]:
    status = operational_state.get("status", "watch")
    current_row = operational_state.get("current_row")
    flags = operational_state.get("threshold_flags", {})
    params = summary["reservoir_parameters"]["values"]
    priority = params.get("priority_order_of_objectives", "")

    if status == "critical":
        action = "Vận hành theo chế độ cắt lũ và ưu tiên giám sát rủi ro hạ du."
        if flags.get("reservoir_above_maximum_allowable"):
            reason = (
                "Quỹ đạo mực nước tối ưu vượt mức vận hành tối đa cho phép "
                f"{params.get('maximum_allowable_reservoir_level')} "
                f"{summary['reservoir_parameters']['units'].get('maximum_allowable_reservoir_level', '')} "
                "trong tầm nhìn ra quyết định đã chọn."
            )
        else:
            reason = (
                "Lưu lượng hạ du tối ưu vượt ngưỡng "
                f"{params.get('downstream_flow_threshold')} "
                f"{summary['reservoir_parameters']['units'].get('downstream_flow_threshold', '')} "
                "trong tầm nhìn ra quyết định đã chọn."
            )
    elif status == "watch":
        action = "Duy trì xả có kiểm soát và đánh giá sát cửa sổ dự báo tiếp theo."
        if flags.get("reservoir_above_pre_flood_target"):
            reason = (
                "Mực nước hồ tối ưu vượt mức đón lũ trong tầm nhìn ra quyết định đã chọn, "
                "vì vậy cần theo dõi chặt phương án xả."
            )
        else:
            reason = "Quỹ đạo tối ưu đang tiến sát các ngưỡng vận hành và cần được theo dõi chủ động."
    else:
        action = "Tiếp tục phương án xả tối ưu và theo dõi các thay đổi dự báo."
        reason = "Các chỉ số hồ chứa và hạ du vẫn nằm trong các ngưỡng cấu hình của phương án tối ưu."

    tradeoff = (
        f"Trong cửa sổ đã chọn, đỉnh lưu lượng hạ du tối ưu thấp hơn quan trắc "
        f"{window_summary['downstream_peak_reduction_percent']:.1f}%, "
        f"và đỉnh lưu lượng xả tối ưu thấp hơn quan trắc {window_summary['release_peak_reduction_percent']:.1f}%."
    )

    if isinstance(current_row, pd.Series) and not current_row.empty:
        reason += (
            f" Tại thời điểm hiện tại, mực nước hồ là {current_row['WLDD']:.2f} m, "
            f"lưu lượng xả tối ưu là {current_row['Qoutput_Reservoir1']:.2f} m3/s, "
            f"và lưu lượng hạ du tối ưu là {current_row['Q_controlpoint']:.2f} m3/s."
        )

    if priority:
        tradeoff += f" Thứ tự ưu tiên mục tiêu: {priority}"

    return action, reason, tradeoff
