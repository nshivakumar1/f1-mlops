"""
Kibana Dashboard Setup — F1 MLOps
==================================
Pushes pre-built visualizations and dashboards to Kibana via saved objects API.
Run after ELK EC2 starts and Kibana is healthy (~2 min after EC2 start).

Usage:
  python3 scripts/setup_kibana_dashboards.py --host http://<EC2-PUBLIC-IP>:5601

Requires:
  pip install requests
"""
import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

INDEX_PATTERN_ID = "f1-inference-star"
INDEX_PATTERN_TITLE = "f1-inference-*"


# ── Visualization definitions ─────────────────────────────────────────────────

def _vis(viz_id, title, vis_type, aggs, params, index_pattern_id=INDEX_PATTERN_ID):
    """Build a saved-object dict for a Kibana aggregation-based visualization."""
    vis_state = json.dumps({
        "title": title,
        "type": vis_type,
        "aggs": aggs,
        "params": params,
    })
    search_source = json.dumps({
        "query": {"query": "", "language": "kuery"},
        "filter": [],
    })
    return {
        "type": "visualization",
        "id": viz_id,
        "attributes": {
            "title": title,
            "visState": vis_state,
            "uiStateJSON": "{}",
            "description": "",
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source},
        },
        "references": [{
            "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
            "type": "index-pattern",
            "id": index_pattern_id,
        }],
    }


# 1. Pitstop probability horizontal bar (top driver risk ranking)
VIZ_PITSTOP_BAR = _vis(
    "f1-viz-pitstop-bar",
    "🏎️ Driver Pitstop Probability",
    "horizontal_bar",
    aggs=[
        {"id": "1", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "pitstop_probability", "customLabel": "Max Pit Prob"}},
        {"id": "2", "enabled": True, "type": "terms", "schema": "group",
         "params": {"field": "driver_name.keyword", "size": 22, "order": "desc",
                    "orderBy": "1", "customLabel": "Driver"}},
    ],
    params={
        "type": "horizontal_bar",
        "grid": {"categoryLines": False},
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "left",
                          "show": True, "labels": {"show": True, "truncate": 200}}],
        "valueAxes": [{"id": "ValueAxis-1", "type": "value", "position": "bottom",
                       "show": True, "labels": {"show": True, "filter": True},
                       "title": {"text": "Pitstop Probability"}}],
        "seriesParams": [{"show": True, "type": "horizontal_bar", "mode": "normal",
                          "data": {"label": "Max Pit Prob", "id": "1"},
                          "valueAxis": "ValueAxis-1"}],
        "addLegend": False,
        "addTimeMarker": False,
    },
)

# 2. Risk band donut chart
VIZ_RISK_DONUT = _vis(
    "f1-viz-risk-donut",
    "⚠️ Risk Band Distribution",
    "pie",
    aggs=[
        {"id": "1", "enabled": True, "type": "count", "schema": "metric",
         "params": {"customLabel": "Drivers"}},
        {"id": "2", "enabled": True, "type": "terms", "schema": "segment",
         "params": {"field": "risk_band.keyword", "size": 3, "customLabel": "Risk Band"}},
    ],
    params={
        "type": "pie",
        "addTooltip": True,
        "addLegend": True,
        "legendPosition": "right",
        "isDonut": True,
        "labels": {"show": True, "values": True, "last_level": True, "truncate": 100},
    },
)

# 3. Tyre compound donut
VIZ_TYRE_DONUT = _vis(
    "f1-viz-tyre-donut",
    "🔴 Tyre Compound Split",
    "pie",
    aggs=[
        {"id": "1", "enabled": True, "type": "count", "schema": "metric",
         "params": {"customLabel": "Stints"}},
        {"id": "2", "enabled": True, "type": "terms", "schema": "segment",
         "params": {"field": "tyre_compound.keyword", "size": 5, "customLabel": "Compound"}},
    ],
    params={
        "type": "pie",
        "addTooltip": True,
        "addLegend": True,
        "legendPosition": "right",
        "isDonut": True,
        "labels": {"show": True, "values": True, "last_level": True, "truncate": 100},
    },
)

# 4. Pitstop probability timeline
VIZ_PROB_TIMELINE = _vis(
    "f1-viz-prob-timeline",
    "📈 Pitstop Probability Over Time",
    "line",
    aggs=[
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric",
         "params": {"field": "pitstop_probability", "customLabel": "Avg Pit Prob"}},
        {"id": "2", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "pitstop_probability", "customLabel": "Max Pit Prob"}},
        {"id": "3", "enabled": True, "type": "date_histogram", "schema": "segment",
         "params": {"field": "@timestamp", "interval": "auto", "customLabel": "Time"}},
        {"id": "4", "enabled": True, "type": "terms", "schema": "group",
         "params": {"field": "driver_name.keyword", "size": 5, "order": "desc",
                    "orderBy": "1", "customLabel": "Driver (top 5 by avg prob)"}},
    ],
    params={
        "type": "line",
        "grid": {"categoryLines": False},
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "bottom",
                          "show": True, "labels": {"show": True}}],
        "valueAxes": [{"id": "ValueAxis-1", "type": "value", "position": "left",
                       "show": True, "labels": {"show": True},
                       "title": {"text": "Probability"}}],
        "seriesParams": [
            {"show": True, "type": "line", "mode": "normal",
             "data": {"label": "Avg Pit Prob", "id": "1"}, "valueAxis": "ValueAxis-1",
             "lineWidth": 2, "showCircles": True},
            {"show": True, "type": "line", "mode": "normal",
             "data": {"label": "Max Pit Prob", "id": "2"}, "valueAxis": "ValueAxis-1",
             "lineWidth": 1, "showCircles": False},
        ],
        "addLegend": True,
        "addTimeMarker": True,
    },
)

# 5. Average confidence metric
VIZ_CONFIDENCE_METRIC = _vis(
    "f1-viz-confidence-metric",
    "🎯 Average Model Confidence",
    "metric",
    aggs=[
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric",
         "params": {"field": "confidence", "customLabel": "Avg Confidence"}},
        {"id": "2", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "pitstop_probability", "customLabel": "Highest Pit Prob"}},
        {"id": "3", "enabled": True, "type": "count", "schema": "metric",
         "params": {"customLabel": "Total Predictions"}},
    ],
    params={
        "type": "metric",
        "addTooltip": True,
        "addLegend": False,
        "style": {"fontSize": 60, "bgFill": "#000", "bgColor": False, "labelColor": False,
                  "subText": ""},
        "colorSchema": "Green to Red",
        "metricColorMode": "None",
        "useRanges": False,
    },
)

# 6. Tyre age histogram
VIZ_TYRE_AGE_HIST = _vis(
    "f1-viz-tyre-age-hist",
    "📊 Tyre Age Distribution",
    "histogram",
    aggs=[
        {"id": "1", "enabled": True, "type": "count", "schema": "metric",
         "params": {"customLabel": "Drivers"}},
        {"id": "2", "enabled": True, "type": "histogram", "schema": "segment",
         "params": {"field": "tyre_age", "interval": 2, "min_doc_count": False,
                    "has_extended_bounds": False, "customLabel": "Tyre Age (laps)"}},
    ],
    params={
        "type": "histogram",
        "grid": {"categoryLines": False},
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "bottom",
                          "show": True, "labels": {"show": True}}],
        "valueAxes": [{"id": "ValueAxis-1", "type": "value", "position": "left",
                       "show": True, "labels": {"show": True},
                       "title": {"text": "Drivers"}}],
        "seriesParams": [{"show": True, "type": "histogram", "mode": "stacked",
                          "data": {"label": "Drivers", "id": "1"},
                          "valueAxis": "ValueAxis-1"}],
        "addLegend": False,
        "addTimeMarker": False,
    },
)

# 7. Driver data table
VIZ_DRIVER_TABLE = _vis(
    "f1-viz-driver-table",
    "📋 Driver Strategy Table",
    "table",
    aggs=[
        {"id": "1", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "pitstop_probability", "customLabel": "Pit Prob"}},
        {"id": "2", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "confidence", "customLabel": "Confidence"}},
        {"id": "3", "enabled": True, "type": "max", "schema": "metric",
         "params": {"field": "tyre_age", "customLabel": "Tyre Age"}},
        {"id": "4", "enabled": True, "type": "terms", "schema": "bucket",
         "params": {"field": "driver_name.keyword", "size": 22, "order": "desc",
                    "orderBy": "1", "customLabel": "Driver"}},
        {"id": "5", "enabled": True, "type": "terms", "schema": "bucket",
         "params": {"field": "team.keyword", "size": 10, "order": "desc",
                    "orderBy": "1", "customLabel": "Team"}},
        {"id": "6", "enabled": True, "type": "terms", "schema": "bucket",
         "params": {"field": "tyre_compound.keyword", "size": 5, "order": "desc",
                    "orderBy": "1", "customLabel": "Compound"}},
        {"id": "7", "enabled": True, "type": "terms", "schema": "bucket",
         "params": {"field": "risk_band.keyword", "size": 3, "order": "desc",
                    "orderBy": "1", "customLabel": "Risk"}},
    ],
    params={
        "perPage": 22,
        "showPartialRows": False,
        "showMetricsAtAllLevels": False,
        "sort": {"columnIndex": None, "direction": None},
        "showTotal": False,
        "totalFunc": "sum",
        "percentageCol": "",
    },
)

# 8. Gap to leader line chart
VIZ_GAP_CHART = _vis(
    "f1-viz-gap-chart",
    "⏱️ Gap to Leader by Driver",
    "line",
    aggs=[
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric",
         "params": {"field": "gap_to_leader", "customLabel": "Gap to Leader (s)"}},
        {"id": "2", "enabled": True, "type": "date_histogram", "schema": "segment",
         "params": {"field": "@timestamp", "interval": "auto", "customLabel": "Time"}},
        {"id": "3", "enabled": True, "type": "terms", "schema": "group",
         "params": {"field": "driver_name.keyword", "size": 5, "order": "desc",
                    "orderBy": "1", "customLabel": "Driver"}},
    ],
    params={
        "type": "line",
        "grid": {"categoryLines": False},
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "bottom",
                          "show": True, "labels": {"show": True}}],
        "valueAxes": [{"id": "ValueAxis-1", "type": "value", "position": "left",
                       "show": True, "labels": {"show": True},
                       "title": {"text": "Gap (seconds)"}}],
        "seriesParams": [{"show": True, "type": "line", "mode": "normal",
                          "data": {"label": "Gap to Leader (s)", "id": "1"},
                          "valueAxis": "ValueAxis-1", "lineWidth": 2, "showCircles": True}],
        "addLegend": True,
        "addTimeMarker": True,
    },
)

# 9. Confidence over time (model drift proxy)
VIZ_CONFIDENCE_TIMELINE = _vis(
    "f1-viz-confidence-timeline",
    "📉 Model Confidence Over Time",
    "line",
    aggs=[
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric",
         "params": {"field": "confidence", "customLabel": "Avg Confidence"}},
        {"id": "2", "enabled": True, "type": "min", "schema": "metric",
         "params": {"field": "confidence", "customLabel": "Min Confidence"}},
        {"id": "3", "enabled": True, "type": "date_histogram", "schema": "segment",
         "params": {"field": "@timestamp", "interval": "auto", "customLabel": "Time"}},
    ],
    params={
        "type": "line",
        "grid": {"categoryLines": False},
        "categoryAxes": [{"id": "CategoryAxis-1", "type": "category", "position": "bottom",
                          "show": True, "labels": {"show": True}}],
        "valueAxes": [{"id": "ValueAxis-1", "type": "value", "position": "left",
                       "show": True, "labels": {"show": True},
                       "title": {"text": "Confidence"}}],
        "seriesParams": [
            {"show": True, "type": "line", "mode": "normal",
             "data": {"label": "Avg Confidence", "id": "1"},
             "valueAxis": "ValueAxis-1", "lineWidth": 2, "showCircles": True},
            {"show": True, "type": "line", "mode": "normal",
             "data": {"label": "Min Confidence", "id": "2"},
             "valueAxis": "ValueAxis-1", "lineWidth": 1, "showCircles": False},
        ],
        "addLegend": True,
        "addTimeMarker": True,
    },
)


# ── Dashboard panels layout helper ────────────────────────────────────────────

def _panel(panel_id, vis_id, x, y, w, h):
    return {
        "panelIndex": str(panel_id),
        "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(panel_id)},
        "type": "visualization",
        "embeddableConfig": {"enhancements": {}},
    }


def _dashboard(dash_id, title, description, panels, refs):
    panels_json = json.dumps(panels)
    options_json = json.dumps({"useMargins": True, "syncColors": False, "hidePanelTitles": False})
    search_source = json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})
    return {
        "type": "dashboard",
        "id": dash_id,
        "attributes": {
            "title": title,
            "description": description,
            "panelsJSON": panels_json,
            "optionsJSON": options_json,
            "timeRestore": True,
            "timeTo": "now",
            "timeFrom": "now-1h",
            "refreshInterval": {"pause": False, "value": 30000},
            "kibanaSavedObjectMeta": {"searchSourceJSON": search_source},
        },
        "references": refs,
    }


# Dashboard 1: Live Race Predictions
DASH_RACE = _dashboard(
    "f1-dash-race",
    "🏎️ F1 Live Race Predictions",
    "Driver pitstop probabilities, tyre strategy and risk bands — updates every 30s",
    panels=[
        {**_panel(1, "f1-viz-pitstop-bar", 0, 0, 24, 15),
         "panelRefName": "panel_1"},
        {**_panel(2, "f1-viz-risk-donut", 24, 0, 12, 15),
         "panelRefName": "panel_2"},
        {**_panel(3, "f1-viz-tyre-donut", 36, 0, 12, 15),
         "panelRefName": "panel_3"},
        {**_panel(4, "f1-viz-driver-table", 0, 15, 48, 15),
         "panelRefName": "panel_4"},
        {**_panel(5, "f1-viz-prob-timeline", 0, 30, 48, 15),
         "panelRefName": "panel_5"},
    ],
    refs=[
        {"name": "panel_1", "type": "visualization", "id": "f1-viz-pitstop-bar"},
        {"name": "panel_2", "type": "visualization", "id": "f1-viz-risk-donut"},
        {"name": "panel_3", "type": "visualization", "id": "f1-viz-tyre-donut"},
        {"name": "panel_4", "type": "visualization", "id": "f1-viz-driver-table"},
        {"name": "panel_5", "type": "visualization", "id": "f1-viz-prob-timeline"},
    ],
)

# Dashboard 2: API Health & Model Performance
DASH_HEALTH = _dashboard(
    "f1-dash-health",
    "📊 F1 API Health & Model Performance",
    "Prediction confidence, processing metrics and model output distribution",
    panels=[
        {**_panel(1, "f1-viz-confidence-metric", 0, 0, 24, 10),
         "panelRefName": "panel_1"},
        {**_panel(2, "f1-viz-tyre-age-hist", 24, 0, 24, 10),
         "panelRefName": "panel_2"},
        {**_panel(3, "f1-viz-confidence-timeline", 0, 10, 48, 15),
         "panelRefName": "panel_3"},
        {**_panel(4, "f1-viz-gap-chart", 0, 25, 48, 15),
         "panelRefName": "panel_4"},
    ],
    refs=[
        {"name": "panel_1", "type": "visualization", "id": "f1-viz-confidence-metric"},
        {"name": "panel_2", "type": "visualization", "id": "f1-viz-tyre-age-hist"},
        {"name": "panel_3", "type": "visualization", "id": "f1-viz-confidence-timeline"},
        {"name": "panel_4", "type": "visualization", "id": "f1-viz-gap-chart"},
    ],
)

# Dashboard 3: Tyre Strategy Deep Dive
DASH_TYRES = _dashboard(
    "f1-dash-tyres",
    "🔴 Tyre Strategy Analysis",
    "Tyre age, compound choices, stints and degradation signals",
    panels=[
        {**_panel(1, "f1-viz-tyre-donut", 0, 0, 16, 15),
         "panelRefName": "panel_1"},
        {**_panel(2, "f1-viz-tyre-age-hist", 16, 0, 16, 15),
         "panelRefName": "panel_2"},
        {**_panel(3, "f1-viz-risk-donut", 32, 0, 16, 15),
         "panelRefName": "panel_3"},
        {**_panel(4, "f1-viz-prob-timeline", 0, 15, 48, 15),
         "panelRefName": "panel_4"},
        {**_panel(5, "f1-viz-driver-table", 0, 30, 48, 15),
         "panelRefName": "panel_5"},
    ],
    refs=[
        {"name": "panel_1", "type": "visualization", "id": "f1-viz-tyre-donut"},
        {"name": "panel_2", "type": "visualization", "id": "f1-viz-tyre-age-hist"},
        {"name": "panel_3", "type": "visualization", "id": "f1-viz-risk-donut"},
        {"name": "panel_4", "type": "visualization", "id": "f1-viz-prob-timeline"},
        {"name": "panel_5", "type": "visualization", "id": "f1-viz-driver-table"},
    ],
)


ALL_OBJECTS = [
    VIZ_PITSTOP_BAR,
    VIZ_RISK_DONUT,
    VIZ_TYRE_DONUT,
    VIZ_PROB_TIMELINE,
    VIZ_CONFIDENCE_METRIC,
    VIZ_TYRE_AGE_HIST,
    VIZ_DRIVER_TABLE,
    VIZ_GAP_CHART,
    VIZ_CONFIDENCE_TIMELINE,
    DASH_RACE,
    DASH_HEALTH,
    DASH_TYRES,
]


# ── Import logic ───────────────────────────────────────────────────────────────

def wait_for_kibana(host: str, timeout: int = 120):
    print(f"Waiting for Kibana at {host} ...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{host}/api/status", timeout=5)
            if r.status_code == 200 and r.json().get("status", {}).get("overall", {}).get("level") in ("available", "green"):
                print(" ready.")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(5)
    print(" timed out.")
    return False


def ensure_index_pattern(host: str):
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    url = f"{host}/api/saved_objects/index-pattern/{INDEX_PATTERN_ID}"
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        print(f"  index-pattern {INDEX_PATTERN_TITLE} already exists")
        return
    payload = {
        "attributes": {
            "title": INDEX_PATTERN_TITLE,
            "timeFieldName": "@timestamp",
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    if r.status_code in (200, 201):
        print(f"  ✅ index-pattern {INDEX_PATTERN_TITLE} created")
    else:
        print(f"  ⚠️  index-pattern create returned {r.status_code}: {r.text[:200]}")


def push_objects(host: str, objects: list):
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    url = f"{host}/api/saved_objects/_bulk_create?overwrite=true"
    r = requests.post(url, headers=headers, json=objects, timeout=30)
    if r.status_code in (200, 201):
        data = r.json()
        saved = [o for o in data.get("saved_objects", []) if not o.get("error")]
        errors = [o for o in data.get("saved_objects", []) if o.get("error")]
        print(f"  ✅ {len(saved)} saved | ❌ {len(errors)} errors")
        for e in errors:
            print(f"     {e.get('type')} {e.get('id')}: {e.get('error', {}).get('message')}")
    else:
        print(f"  ❌ bulk_create returned {r.status_code}: {r.text[:300]}")


def main():
    parser = argparse.ArgumentParser(description="Push Kibana dashboards for F1 MLOps")
    parser.add_argument("--host", default="http://localhost:5601",
                        help="Kibana host (default: http://localhost:5601)")
    parser.add_argument("--no-wait", action="store_true",
                        help="Skip Kibana health check")
    args = parser.parse_args()

    host = args.host.rstrip("/")
    print(f"=== F1 MLOps Kibana Dashboard Setup ===")
    print(f"Target: {host}")

    if not args.no_wait:
        if not wait_for_kibana(host):
            print("Kibana not ready. Try again in 60s or pass --no-wait.")
            sys.exit(1)

    print("\nCreating index pattern...")
    ensure_index_pattern(host)

    print("\nUploading 9 visualizations + 3 dashboards...")
    push_objects(host, ALL_OBJECTS)

    print(f"""
=== Done ===
Open Kibana: {host}

Dashboards created:
  🏎️  F1 Live Race Predictions   → pitstop probabilities, driver table, risk bands
  📊  API Health & Model Perf    → confidence metrics, tyre age histogram, timelines
  🔴  Tyre Strategy Analysis     → compound breakdown, age distribution, stint analysis

Set time filter to "Last 1 hour" during live sessions.
""")


if __name__ == "__main__":
    main()
