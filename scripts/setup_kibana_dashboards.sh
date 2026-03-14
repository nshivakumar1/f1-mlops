#!/bin/bash
# Run this after starting the ELK EC2 to create rich Kibana dashboards.
# Usage: ./scripts/setup_kibana_dashboards.sh <kibana_url>
# Example: ./scripts/setup_kibana_dashboards.sh http://1.2.3.4:5601

set -e
KIBANA="${1:-http://localhost:5601}"
echo "Setting up Kibana dashboards at $KIBANA..."

# Wait for Kibana to be ready
echo "Waiting for Kibana..."
for i in $(seq 1 30); do
  if curl -sf "$KIBANA/api/status" | grep -q '"overall"'; then break; fi
  echo "  attempt $i/30..."
  sleep 10
done

HEADERS=('-H' 'kbn-xsrf: true' '-H' 'Content-Type: application/json')

# ── 1. Index pattern ──────────────────────────────────────────────────────────
echo "Creating index pattern: f1-inference-*"
curl -sf -X POST "$KIBANA/api/saved_objects/index-pattern/f1-inference" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "f1-inference-*",
    "timeFieldName": "@timestamp"
  }
}' > /dev/null && echo "  OK"

# ── 2. Pitstop probability line chart (per driver over time) ──────────────────
echo "Creating line chart: Pitstop Probability Over Time"
curl -sf -X POST "$KIBANA/api/saved_objects/visualization/f1-pitstop-prob-line" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "Pitstop Probability Over Time (per Driver)",
    "visState": "{\"title\":\"Pitstop Probability Over Time\",\"type\":\"line\",\"aggs\":[{\"id\":\"1\",\"enabled\":true,\"type\":\"avg\",\"params\":{\"field\":\"pitstop_probability\"},\"schema\":\"metric\"},{\"id\":\"2\",\"enabled\":true,\"type\":\"date_histogram\",\"params\":{\"field\":\"@timestamp\",\"fixed_interval\":\"1m\",\"min_doc_count\":1},\"schema\":\"segment\"},{\"id\":\"3\",\"enabled\":true,\"type\":\"terms\",\"params\":{\"field\":\"driver_name.keyword\",\"orderBy\":\"1\",\"order\":\"desc\",\"size\":10},\"schema\":\"group\"}],\"params\":{\"type\":\"line\",\"grid\":{\"categoryLines\":false},\"categoryAxes\":[{\"id\":\"CategoryAxis-1\",\"type\":\"category\",\"position\":\"bottom\",\"show\":true,\"style\":{},\"scale\":{\"type\":\"linear\"},\"labels\":{\"show\":true,\"filter\":true,\"truncate\":100},\"title\":{}}],\"valueAxes\":[{\"id\":\"ValueAxis-1\",\"name\":\"LeftAxis-1\",\"type\":\"value\",\"position\":\"left\",\"show\":true,\"style\":{},\"scale\":{\"type\":\"linear\",\"mode\":\"normal\"},\"labels\":{\"show\":true,\"rotate\":0,\"filter\":false,\"truncate\":100},\"title\":{\"text\":\"Pitstop Probability\"}}],\"seriesParams\":[{\"show\":true,\"type\":\"line\",\"mode\":\"normal\",\"data\":{\"label\":\"Avg Probability\",\"id\":\"1\"},\"valueAxis\":\"ValueAxis-1\",\"drawLinesBetweenPoints\":true,\"lineWidth\":2,\"showCircles\":true}],\"addTooltip\":true,\"addLegend\":true,\"legendPosition\":\"right\",\"times\":[],\"addTimeMarker\":false,\"thresholdLine\":{\"show\":true,\"value\":0.7,\"width\":2,\"style\":\"dashed\",\"color\":\"#E7664C\"}}}",
    "uiStateJSON": "{}",
    "description": "Line chart of pitstop probability per driver, updated every lap",
    "kibanaSavedObjectMeta": {
      "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}"
    }
  },
  "references": [{"name":"kibanaSavedObjectMeta.searchSourceJSON.index","type":"index-pattern","id":"f1-inference"}]
}' > /dev/null && echo "  OK"

# ── 3. Top pitstop candidates bar chart ──────────────────────────────────────
echo "Creating bar chart: Top Pitstop Candidates"
curl -sf -X POST "$KIBANA/api/saved_objects/visualization/f1-top-candidates-bar" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "Top Pitstop Candidates (Latest)",
    "visState": "{\"title\":\"Top Pitstop Candidates\",\"type\":\"horizontal_bar\",\"aggs\":[{\"id\":\"1\",\"enabled\":true,\"type\":\"max\",\"params\":{\"field\":\"pitstop_probability\"},\"schema\":\"metric\"},{\"id\":\"2\",\"enabled\":true,\"type\":\"terms\",\"params\":{\"field\":\"driver_name.keyword\",\"orderBy\":\"1\",\"order\":\"desc\",\"size\":10},\"schema\":\"segment\"}],\"params\":{\"type\":\"histogram\",\"grid\":{\"categoryLines\":false},\"categoryAxes\":[{\"id\":\"CategoryAxis-1\",\"type\":\"category\",\"position\":\"left\",\"show\":true,\"style\":{},\"scale\":{\"type\":\"linear\"},\"labels\":{\"show\":true,\"filter\":true,\"truncate\":200},\"title\":{}}],\"valueAxes\":[{\"id\":\"ValueAxis-1\",\"name\":\"BottomAxis-1\",\"type\":\"value\",\"position\":\"bottom\",\"show\":true,\"style\":{},\"scale\":{\"type\":\"linear\",\"mode\":\"normal\"},\"labels\":{\"show\":true,\"rotate\":0,\"filter\":true,\"truncate\":100},\"title\":{\"text\":\"Max Pitstop Probability\"}}],\"seriesParams\":[{\"show\":true,\"type\":\"histogram\",\"mode\":\"normal\",\"data\":{\"label\":\"Max Probability\",\"id\":\"1\"},\"valueAxis\":\"ValueAxis-1\"}],\"addTooltip\":true,\"addLegend\":false,\"legendPosition\":\"right\",\"times\":[],\"addTimeMarker\":false}}",
    "uiStateJSON": "{}",
    "description": "Horizontal bar chart ranking drivers by pitstop probability",
    "kibanaSavedObjectMeta": {
      "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}"
    }
  },
  "references": [{"name":"kibanaSavedObjectMeta.searchSourceJSON.index","type":"index-pattern","id":"f1-inference"}]
}' > /dev/null && echo "  OK"

# ── 4. Tyre age vs probability scatter ────────────────────────────────────────
echo "Creating line chart: Tyre Age vs Pitstop Probability"
curl -sf -X POST "$KIBANA/api/saved_objects/visualization/f1-tyre-age-vs-prob" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "Tyre Age vs Pitstop Probability",
    "visState": "{\"title\":\"Tyre Age vs Pitstop Probability\",\"type\":\"line\",\"aggs\":[{\"id\":\"1\",\"enabled\":true,\"type\":\"avg\",\"params\":{\"field\":\"pitstop_probability\"},\"schema\":\"metric\"},{\"id\":\"2\",\"enabled\":true,\"type\":\"histogram\",\"params\":{\"field\":\"tyre_age\",\"interval\":2,\"min_doc_count\":1,\"has_extended_bounds\":false},\"schema\":\"segment\"}],\"params\":{\"type\":\"line\",\"grid\":{\"categoryLines\":false},\"categoryAxes\":[{\"id\":\"CategoryAxis-1\",\"type\":\"category\",\"position\":\"bottom\",\"show\":true,\"labels\":{\"show\":true},\"title\":{\"text\":\"Tyre Age (laps)\"}}],\"valueAxes\":[{\"id\":\"ValueAxis-1\",\"name\":\"LeftAxis-1\",\"type\":\"value\",\"position\":\"left\",\"show\":true,\"scale\":{\"type\":\"linear\",\"mode\":\"normal\"},\"labels\":{\"show\":true},\"title\":{\"text\":\"Avg Pitstop Probability\"}}],\"seriesParams\":[{\"show\":true,\"type\":\"line\",\"mode\":\"normal\",\"data\":{\"label\":\"Avg Probability\",\"id\":\"1\"},\"valueAxis\":\"ValueAxis-1\",\"drawLinesBetweenPoints\":true,\"lineWidth\":2,\"showCircles\":true}],\"addTooltip\":true,\"addLegend\":true}}",
    "uiStateJSON": "{}",
    "description": "How pitstop probability increases with tyre age",
    "kibanaSavedObjectMeta": {
      "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}"
    }
  },
  "references": [{"name":"kibanaSavedObjectMeta.searchSourceJSON.index","type":"index-pattern","id":"f1-inference"}]
}' > /dev/null && echo "  OK"

# ── 5. Safety car metric ──────────────────────────────────────────────────────
echo "Creating metric: Safety Car Status"
curl -sf -X POST "$KIBANA/api/saved_objects/visualization/f1-safety-car-metric" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "Safety Car Active",
    "visState": "{\"title\":\"Safety Car Active\",\"type\":\"metric\",\"aggs\":[{\"id\":\"1\",\"enabled\":true,\"type\":\"max\",\"params\":{\"field\":\"safety_car_active\"},\"schema\":\"metric\"}],\"params\":{\"addTooltip\":true,\"addLegend\":false,\"type\":\"metric\",\"metric\":{\"percentageMode\":false,\"useRanges\":true,\"colorSchema\":\"Green to Red\",\"metricColorMode\":\"Background\",\"colorsRange\":[{\"from\":0,\"to\":0.5,\"color\":\"#1DB954\"},{\"from\":0.5,\"to\":1,\"color\":\"#FFC125\"}],\"labels\":{\"show\":true},\"invertColors\":false,\"style\":{\"bgFill\":\"#000\",\"bgColor\":true,\"labelColor\":false,\"subText\":\"Safety Car\",\"fontSize\":60}}}}",
    "uiStateJSON": "{}",
    "description": "1 = Safety car active, 0 = Green flag",
    "kibanaSavedObjectMeta": {
      "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}"
    }
  },
  "references": [{"name":"kibanaSavedObjectMeta.searchSourceJSON.index","type":"index-pattern","id":"f1-inference"}]
}' > /dev/null && echo "  OK"

# ── 6. Assemble dashboard ─────────────────────────────────────────────────────
echo "Creating dashboard: F1 Race Live"
curl -sf -X POST "$KIBANA/api/saved_objects/dashboard/f1-race-live" \
  "${HEADERS[@]}" -d '{
  "attributes": {
    "title": "F1 Race Live",
    "hits": 0,
    "description": "Live pitstop predictions, tyre strategy, safety car status",
    "panelsJSON": "[{\"version\":\"8.0.0\",\"type\":\"visualization\",\"gridData\":{\"x\":0,\"y\":0,\"w\":48,\"h\":15,\"i\":\"1\"},\"panelIndex\":\"1\",\"embeddableConfig\":{},\"panelRefName\":\"panel_1\"},{\"version\":\"8.0.0\",\"type\":\"visualization\",\"gridData\":{\"x\":0,\"y\":15,\"w\":24,\"h\":15,\"i\":\"2\"},\"panelIndex\":\"2\",\"embeddableConfig\":{},\"panelRefName\":\"panel_2\"},{\"version\":\"8.0.0\",\"type\":\"visualization\",\"gridData\":{\"x\":24,\"y\":15,\"w\":20,\"h\":15,\"i\":\"3\"},\"panelIndex\":\"3\",\"embeddableConfig\":{},\"panelRefName\":\"panel_3\"},{\"version\":\"8.0.0\",\"type\":\"visualization\",\"gridData\":{\"x\":44,\"y\":15,\"w\":4,\"h\":15,\"i\":\"4\"},\"panelIndex\":\"4\",\"embeddableConfig\":{},\"panelRefName\":\"panel_4\"}]",
    "optionsJSON": "{\"useMargins\":true,\"syncColors\":false,\"hidePanelTitles\":false}",
    "timeRestore": false,
    "kibanaSavedObjectMeta": {
      "searchSourceJSON": "{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[]}"
    }
  },
  "references": [
    {"name":"panel_1","type":"visualization","id":"f1-pitstop-prob-line"},
    {"name":"panel_2","type":"visualization","id":"f1-top-candidates-bar"},
    {"name":"panel_3","type":"visualization","id":"f1-tyre-age-vs-prob"},
    {"name":"panel_4","type":"visualization","id":"f1-safety-car-metric"}
  ]
}' > /dev/null && echo "  OK"

echo ""
echo "Done! Open: $KIBANA/app/dashboards#/view/f1-race-live"
echo "Set time range to 'Last 2 hours' and enable auto-refresh every 30s."
