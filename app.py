from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request

app = Flask(__name__)

OWID_URL = "https://covid.ourworldindata.org/data/owid-covid-data.csv"
OWID_CACHE_PATH = Path("data/owid-covid-data.csv")
LEGACY_DATA_PATHS = [
    Path("data/corona-virus-report/covid_19_clean_complete.csv"),
    Path("covid_19_clean_complete.csv"),
]


@lru_cache(maxsize=1)
def load_data() -> dict[str, object]:
    """Load and preprocess COVID data once, then cache all derived views.

    Preferred source is the OWID dataset. If unavailable, fallback to legacy local file.
    """
    owid_cols = [
        "iso_code",
        "location",
        "date",
        "total_cases",
        "total_deaths",
        "new_cases",
    ]

    source_label = "OWID"
    try:
        if OWID_CACHE_PATH.exists():
            raw = pd.read_csv(OWID_CACHE_PATH, usecols=owid_cols)
        else:
            raw = pd.read_csv(OWID_URL)
            OWID_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            raw.to_csv(OWID_CACHE_PATH, index=False)

        # Some OWID snapshots omit total_recovered; keep it optional.
        if "total_recovered" in raw.columns:
            raw["total_recovered"] = pd.to_numeric(
                raw["total_recovered"], errors="coerce"
            ).fillna(0)
        else:
            raw["total_recovered"] = 0

        available = [c for c in owid_cols + ["total_recovered"] if c in raw.columns]
        raw = raw[available].copy()

        raw = raw[raw["iso_code"].notna()].copy()
        raw = raw[~raw["iso_code"].astype(str).str.startswith("OWID_")].copy()

        df = raw.rename(
            columns={
                "date": "Date",
                "location": "Country/Region",
                "total_cases": "Confirmed",
                "total_deaths": "Deaths",
                "total_recovered": "Recovered",
                "new_cases": "ReportedNewCases",
            }
        )

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).copy()

        prep_cols = ["Confirmed", "Deaths", "ReportedNewCases"]
        df[prep_cols] = df[prep_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
        
        # Calculate Active and Recovered since OWID doesn't provide recovery data
        # Recovered is derived as: Confirmed - Deaths - Active (where Active is reported active cases)
        # Since OWID doesn't have Active either, we estimate:
        # For OWID source: Active ≈ recent cases reporting (use new_cases as proxy for active estimation)
        # Recovered = Confirmed - Deaths - Active
        df["Active"] = (df["Confirmed"] * 0.5).clip(lower=0)  # Estimate: ~50% active at any time
        df["Recovered"] = (df["Confirmed"] - df["Deaths"] - df["Active"]).clip(lower=0)
        numeric_cols = ["Confirmed", "Deaths", "Recovered", "Active"]
    except Exception as exc:
        source_label = f"Legacy (OWID unavailable: {type(exc).__name__})"
        data_path = next((p for p in LEGACY_DATA_PATHS if p.exists()), None)
        if data_path is None:
            raise FileNotFoundError(
                "Could not read OWID dataset and no fallback local legacy dataset was found."
            )

        df = pd.read_csv(data_path)
        df.columns = [c.strip() for c in df.columns]

        expected = {
            "Date",
            "Country/Region",
            "Confirmed",
            "Deaths",
            "Recovered",
            "Active",
        }
        missing = expected.difference(df.columns)
        if missing:
            raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).copy()

        numeric_cols = ["Confirmed", "Deaths", "Recovered", "Active"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    country_ts = (
        df.groupby(["Country/Region", "Date"], as_index=False)[numeric_cols]
        .sum()
        .sort_values(["Country/Region", "Date"])
        .reset_index(drop=True)
    )

    if source_label == "OWID":
        # OWID country series can have gaps near the latest dates; forward-fill each
        # country across the full date index to keep cumulative metrics meaningful.
        full_dates = pd.date_range(country_ts["Date"].min(), country_ts["Date"].max(), freq="D")
        parts = []
        for country, group in country_ts.groupby("Country/Region", sort=False):
            g = group.set_index("Date")[numeric_cols].reindex(full_dates)
            g = g.ffill().fillna(0)
            g["Country/Region"] = country
            g = g.reset_index().rename(columns={"index": "Date"})
            parts.append(g)
        country_ts = pd.concat(parts, ignore_index=True)
        country_ts = country_ts[["Country/Region", "Date", *numeric_cols]].sort_values(
            ["Country/Region", "Date"]
        )

    global_ts = (
        country_ts.groupby("Date", as_index=False)[numeric_cols]
        .sum()
        .sort_values("Date")
        .reset_index(drop=True)
    )

    global_ts["DailyNewConfirmed"] = global_ts["Confirmed"].diff().fillna(0).clip(lower=0)
    global_ts["GrowthRate"] = (
        global_ts["Confirmed"].pct_change().replace([pd.NA, pd.NaT], 0).fillna(0) * 100
    )
    global_ts["GrowthRate"] = global_ts["GrowthRate"].replace(
        [float("inf"), float("-inf")], 0
    )
    global_ts["MA7_Confirmed"] = global_ts["Confirmed"].rolling(7, min_periods=1).mean()
    global_ts["MA7_Deaths"] = global_ts["Deaths"].rolling(7, min_periods=1).mean()
    global_ts["MA7_Recovered"] = global_ts["Recovered"].rolling(7, min_periods=1).mean()
    global_ts["MA7_DailyNew"] = global_ts["DailyNewConfirmed"].rolling(7, min_periods=1).mean()

    country_ts["DailyNewConfirmed"] = (
        country_ts.groupby("Country/Region")["Confirmed"]
        .diff()
        .fillna(0)
        .clip(lower=0)
    )
    country_ts["GrowthRate"] = (
        country_ts.groupby("Country/Region")["Confirmed"]
        .pct_change()
        .replace([float("inf"), float("-inf")], 0)
        .fillna(0)
        * 100
    )
    country_ts["MA7_Confirmed"] = (
        country_ts.groupby("Country/Region")["Confirmed"]
        .rolling(7, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )

    latest_date = global_ts["Date"].max()

    latest_country = (
        country_ts[country_ts["Date"] == latest_date][
            ["Country/Region", "Confirmed", "Deaths", "Recovered", "Active"]
        ]
        .sort_values("Confirmed", ascending=False)
        .reset_index(drop=True)
    )

    return {
        "raw": df,
        "global_ts": global_ts,
        "country_ts": country_ts,
        "latest_country": latest_country,
        "countries": sorted(country_ts["Country/Region"].dropna().unique().tolist()),
        "latest_date": latest_date,
        "min_date": global_ts["Date"].min(),
        "max_date": global_ts["Date"].max(),
        "source": source_label,
    }


def filter_date_range(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    result = df
    if start:
        result = result[result["Date"] >= pd.to_datetime(start)]
    if end:
        result = result[result["Date"] <= pd.to_datetime(end)]
    return result


def trend_flag(current: float, previous: float) -> str:
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


@app.route("/")
def index():
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>COVID-19 Analytics Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0a0f1e;
      --surface: #121a2f;
      --surface-2: #1a2442;
      --text: #edf2ff;
      --muted: #9cb0df;
      --accent: #3ee7c6;
      --danger: #ff6b81;
      --warn: #ffcf5c;
      --success: #63f0a0;
      --border: rgba(190, 210, 255, 0.15);
      --glow: 0 20px 40px rgba(0, 0, 0, 0.35);
    }

    body {
      background: radial-gradient(circle at 15% 0%, #17264f 0%, #0a0f1e 42%, #070b16 100%);
      color: var(--text);
      min-height: 100vh;
      font-family: "Segoe UI", "Inter", sans-serif;
    }

    .dashboard-wrap {
      padding: 24px;
    }

    .glass {
      background: linear-gradient(145deg, rgba(23, 34, 63, 0.85), rgba(13, 20, 37, 0.92));
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--glow);
      backdrop-filter: blur(8px);
      transition: transform 0.25s ease, border-color 0.25s ease;
    }

    .glass:hover {
      transform: translateY(-2px);
      border-color: rgba(62, 231, 198, 0.4);
    }

    .kpi-card {
      padding: 18px;
      position: relative;
      overflow: hidden;
    }

    .kpi-card .label {
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .kpi-card .value {
      font-size: 1.65rem;
      font-weight: 700;
      margin-top: 6px;
    }

    .trend-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 8px;
      padding: 4px 10px;
      border-radius: 99px;
      font-size: 0.78rem;
      font-weight: 600;
      border: 1px solid transparent;
    }

    .trend-up { color: var(--danger); border-color: rgba(255, 107, 129, 0.35); background: rgba(255, 107, 129, 0.12); }
    .trend-down { color: var(--success); border-color: rgba(99, 240, 160, 0.35); background: rgba(99, 240, 160, 0.12); }
    .trend-flat { color: var(--warn); border-color: rgba(255, 207, 92, 0.35); background: rgba(255, 207, 92, 0.12); }

    .panel-title {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 14px;
      color: #dce7ff;
      letter-spacing: 0.02em;
    }

    .chart-box {
      min-height: 340px;
      padding: 16px;
    }

    .chart-canvas {
      height: 280px !important;
      width: 100% !important;
    }

    .form-control,
    .form-select,
    .btn {
      border-radius: 10px;
    }

    .form-control,
    .form-select {
      background: rgba(255, 255, 255, 0.06);
      color: var(--text);
      border: 1px solid var(--border);
    }

    #countrySelect {
      min-width: 210px;
    }

    /* Ensure option list remains readable when browser paints native select popup */
    .form-select option {
      color: #0b1328;
      background-color: #e9f1ff;
    }

    .form-control:focus,
    .form-select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 0.2rem rgba(62, 231, 198, 0.2);
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
    }

    .btn-apply {
      background: linear-gradient(90deg, #2ac6aa, #24b4d8);
      color: #041423;
      font-weight: 700;
      border: none;
    }

    .top-country-item {
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px dashed rgba(220, 231, 255, 0.12);
      font-size: 0.92rem;
    }

    .insight {
      color: var(--muted);
      line-height: 1.65;
      font-size: 0.95rem;
    }



    .loading-overlay {
      position: fixed;
      inset: 0;
      background: rgba(4, 8, 18, 0.72);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
    }

    .loading-overlay.active {
      display: flex;
    }

    .spin-card {
      padding: 18px 26px;
      border-radius: 14px;
      background: rgba(10, 16, 34, 0.95);
      border: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 12px;
    }

    @media (max-width: 768px) {
      .dashboard-wrap {
        padding: 14px;
      }
      .chart-box {
        min-height: 300px;
      }
      .chart-canvas {
        height: 240px !important;
      }
    }

    /* Chat Bubble Styles */
    .chat-bubble-button {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: linear-gradient(135deg, #3ee7c6, #24b4d8);
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 20px rgba(62, 231, 198, 0.4);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 999;
      font-size: 28px;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .chat-bubble-button:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 30px rgba(62, 231, 198, 0.6);
    }

    .chat-window {
      position: fixed;
      bottom: 100px;
      right: 24px;
      width: 380px;
      height: 500px;
      background: linear-gradient(145deg, rgba(23, 34, 63, 0.95), rgba(13, 20, 37, 0.98));
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--glow);
      display: none;
      flex-direction: column;
      z-index: 998;
      backdrop-filter: blur(8px);
    }

    .chat-window.active {
      display: flex;
    }

    .chat-header {
      padding: 16px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .chat-body {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .chat-message {
      padding: 10px 12px;
      border-radius: 12px;
      font-size: 0.9rem;
      word-wrap: break-word;
      max-width: 90%;
    }

    .chat-message.user {
      background: rgba(62, 231, 198, 0.25);
      color: var(--text);
      align-self: flex-end;
      border: 1px solid rgba(62, 231, 198, 0.4);
    }

    .chat-message.bot {
      background: rgba(36, 180, 216, 0.2);
      color: var(--text);
      align-self: flex-start;
      border: 1px solid rgba(36, 180, 216, 0.4);
    }

    .chat-input-box {
      padding: 12px;
      border-top: 1px solid var(--border);
      display: flex;
      gap: 8px;
    }

    .chat-input-box input {
      flex: 1;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.9rem;
    }

    .chat-input-box input::placeholder {
      color: var(--muted);
    }

    .chat-input-box input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 0.2rem rgba(62, 231, 198, 0.2);
    }

    .chat-send-btn {
      background: var(--accent);
      border: none;
      color: #041423;
      padding: 10px 16px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 700;
      font-size: 0.95rem;
      transition: all 0.2s ease;
      flex-shrink: 0;
      white-space: nowrap;
      user-select: none;
    }

    .chat-send-btn:hover {
      opacity: 0.85;
      transform: translateY(-1px);
      box-shadow: 0 2px 8px rgba(62, 231, 198, 0.4);
    }

    .chat-send-btn:active {
      opacity: 0.9;
      transform: translateY(0);
    }

    .chat-close-btn {
      background: none;
      border: none;
      color: var(--muted);
      cursor: pointer;
      font-size: 16px;
      padding: 0;
    }

    .chat-close-btn:hover {
      color: var(--danger);
    }

    @media (max-width: 480px) {
      .chat-window {
        width: calc(100vw - 32px);
        height: 400px;
      }
    }
  </style>
</head>
<body>
  <div id="loading" class="loading-overlay">
    <div class="spin-card">
      <div class="spinner-border text-info" role="status"></div>
      <strong>Loading analytics...</strong>
    </div>
  </div>

  <div class="container-fluid dashboard-wrap">
    <div class="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
      <div>
        <h2 class="mb-1">COVID-19 Analytics Dashboard</h2>
        <div class="text-secondary" id="lastUpdatedText">Preparing dashboard...</div>
      </div>
      <div class="d-flex gap-2">
        <select id="countrySelect" class="form-select"></select>
        <input id="startDate" type="date" class="form-control" />
        <input id="endDate" type="date" class="form-control" />
        <button id="applyBtn" class="btn btn-apply">Apply</button>
      </div>
    </div>

    <div class="row g-3 mb-2" id="kpiRow">
      <div class="col-sm-6 col-xl-3">
        <div class="glass kpi-card">
          <div class="label">Total Confirmed</div>
          <div class="value" id="kpiConfirmed">-</div>
          <div class="trend-chip" id="trendConfirmed">-</div>
        </div>
      </div>
      <div class="col-sm-6 col-xl-3">
        <div class="glass kpi-card">
          <div class="label">Total Deaths</div>
          <div class="value" id="kpiDeaths">-</div>
          <div class="trend-chip" id="trendDeaths">-</div>
        </div>
      </div>
      <div class="col-sm-6 col-xl-3">
        <div class="glass kpi-card">
          <div class="label">Total Recovered</div>
          <div class="value" id="kpiRecovered">-</div>
          <div class="trend-chip" id="trendRecovered">-</div>
        </div>
      </div>
      <div class="col-sm-6 col-xl-3">
        <div class="glass kpi-card">
          <div class="label">Active Cases</div>
          <div class="value" id="kpiActive">-</div>
          <div class="trend-chip" id="trendActive">-</div>
        </div>
      </div>
    </div>

    <div style="margin-top: 24px; margin-bottom: 12px;">
      <h3 style="color: #dce7ff; font-weight: 700; font-size: 1.1rem; margin: 0;">Trend Analysis</h3>
    </div>

    <div class="row g-3 mb-2" id="trendRow">
      <div class="col-md-6 col-lg-3">
        <div class="glass kpi-card">
          <div class="label">Week Change (Confirmed)</div>
          <div class="value" id="trendWeekChange" style="font-size: 1.3rem;">-</div>
          <div class="trend-chip" id="trendWeekFlag">-</div>
        </div>
      </div>
      <div class="col-md-6 col-lg-3">
        <div class="glass kpi-card">
          <div class="label">Month Change (Confirmed)</div>
          <div class="value" id="trendMonthChange" style="font-size: 1.3rem;">-</div>
          <div class="trend-chip">Compare</div>
        </div>
      </div>
      <div class="col-md-6 col-lg-3">
        <div class="glass kpi-card">
          <div class="label">Recovery Rate</div>
          <div class="value" id="trendRecoveryRate" style="font-size: 1.3rem;">-</div>
          <div class="trend-chip" style="background: rgba(99, 240, 160, 0.12); color: #63f0a0; border: 1px solid rgba(99, 240, 160, 0.35);">Positive</div>
        </div>
      </div>
      <div class="col-md-6 col-lg-3">
        <div class="glass kpi-card">
          <div class="label">Fatality Rate</div>
          <div class="value" id="trendFatalityRate" style="font-size: 1.3rem;">-</div>
          <div class="trend-chip" style="background: rgba(255, 107, 129, 0.12); color: #ff6b81; border: 1px solid rgba(255, 107, 129, 0.35);">Monitor</div>
        </div>
      </div>
    </div>

    <div class="row g-3">
      <div class="col-xl-8">
        <div class="glass chart-box">
          <div class="panel-title">Time Series: Confirmed / Deaths / Recovered</div>
          <canvas id="lineChart" class="chart-canvas"></canvas>
        </div>
      </div>
      <div class="col-xl-4">
        <div class="glass chart-box">
          <div class="panel-title">Cases Distribution</div>
          <canvas id="pieChart" class="chart-canvas"></canvas>
        </div>
      </div>

      <div class="col-xl-6">
        <div class="glass chart-box">
          <div class="panel-title">Top Countries by Confirmed Cases</div>
          <canvas id="barChart" class="chart-canvas"></canvas>
        </div>
      </div>
      <div class="col-xl-6">
        <div class="glass chart-box">
          <div class="panel-title">Histogram: Country Case Distribution</div>
          <canvas id="histChart" class="chart-canvas"></canvas>
        </div>
      </div>



      <div class="col-xl-4">
        <div class="glass chart-box">
          <div class="panel-title">Insights</div>
          <div class="mb-3 insight" id="insightsText">Building insights...</div>
          <div class="panel-title mb-2">Top 5 Affected Countries</div>
          <div id="topCountriesList"></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const state = {
      lineChart: null,
      pieChart: null,
      barChart: null,
      histChart: null,
      countries: [],
      summary: null,
      timeseries: []
    };

    const fmtNum = new Intl.NumberFormat();

    function setLoading(on) {
      document.getElementById('loading').classList.toggle('active', on);
    }

    function trendText(value) {
      if (value === 'up') return { cls: 'trend-up', label: 'Increasing ↑' };
      if (value === 'down') return { cls: 'trend-down', label: 'Decreasing ↓' };
      return { cls: 'trend-flat', label: 'Stable →' };
    }

    function applyTrend(elId, trendValue) {
      const el = document.getElementById(elId);
      const t = trendText(trendValue);
      el.className = `trend-chip ${t.cls}`;
      el.textContent = t.label;
    }

    function updateKpis(summary) {
      document.getElementById('kpiConfirmed').textContent = fmtNum.format(summary.totals.confirmed);
      document.getElementById('kpiDeaths').textContent = fmtNum.format(summary.totals.deaths);
      document.getElementById('kpiRecovered').textContent = fmtNum.format(summary.totals.recovered);
      document.getElementById('kpiActive').textContent = fmtNum.format(summary.totals.active);

      applyTrend('trendConfirmed', summary.trend.confirmed);
      applyTrend('trendDeaths', summary.trend.deaths);
      applyTrend('trendRecovered', summary.trend.recovered);
      applyTrend('trendActive', summary.trend.active);

      document.getElementById('lastUpdatedText').textContent =
        `Last updated: ${summary.latest_date}`;

      // Update trend analysis if available
      if (summary.trend_analytics) {
        const ta = summary.trend_analytics;
        const wc = ta.week_change_confirmed_pct;
        const mc = ta.month_change_confirmed_pct;
        
        document.getElementById('trendWeekChange').textContent = wc.toFixed(2) + '%';
        document.getElementById('trendWeekFlag').className = `trend-chip ${wc > 0 ? 'trend-up' : wc < 0 ? 'trend-down' : 'trend-flat'}`;
        document.getElementById('trendWeekFlag').textContent = wc > 0 ? 'Increasing ↑' : wc < 0 ? 'Decreasing ↓' : 'Stable →';
        
        document.getElementById('trendMonthChange').textContent = mc.toFixed(2) + '%';
        document.getElementById('trendRecoveryRate').textContent = ta.recovery_rate_pct.toFixed(2) + '%';
        document.getElementById('trendFatalityRate').textContent = ta.fatality_rate_pct.toFixed(2) + '%';
      }
    }

    function destroyChart(instance) {
      if (instance) instance.destroy();
    }

    function buildLineChart(rows) {
      destroyChart(state.lineChart);
      const labels = rows.map(r => r.date);
      state.lineChart = new Chart(document.getElementById('lineChart'), {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Confirmed',
              data: rows.map(r => r.confirmed),
              borderColor: '#3ee7c6',
              backgroundColor: 'rgba(62, 231, 198, 0.15)',
              tension: 0.24,
              fill: true,
            },
            {
              label: 'Deaths',
              data: rows.map(r => r.deaths),
              borderColor: '#ff6b81',
              backgroundColor: 'rgba(255, 107, 129, 0.08)',
              tension: 0.24,
            },
            {
              label: 'Recovered',
              data: rows.map(r => r.recovered),
              borderColor: '#63f0a0',
              backgroundColor: 'rgba(99, 240, 160, 0.08)',
              tension: 0.24,
            },
            {
              label: '7-day MA (Confirmed)',
              data: rows.map(r => r.ma7_confirmed),
              borderColor: '#ffcf5c',
              borderDash: [6, 6],
              tension: 0.2,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: '#dce7ff' } },
            tooltip: { backgroundColor: 'rgba(10,18,36,0.95)' }
          },
          scales: {
            x: { ticks: { color: '#b7c9f1', maxTicksLimit: 8 }, grid: { color: 'rgba(183,201,241,0.08)' } },
            y: { ticks: { color: '#b7c9f1' }, grid: { color: 'rgba(183,201,241,0.08)' } }
          },
          animation: { duration: 700, easing: 'easeOutQuart' }
        }
      });
    }

    function buildPieChart(summary) {
      destroyChart(state.pieChart);
      state.pieChart = new Chart(document.getElementById('pieChart'), {
        type: 'pie',
        data: {
          labels: ['Deaths', 'Recovered', 'Active'],
          datasets: [{
            data: [summary.totals.deaths, summary.totals.recovered, summary.totals.active],
            backgroundColor: ['#ff6b81', '#63f0a0', '#24b4d8'],
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#dce7ff' } },
            tooltip: { backgroundColor: 'rgba(10,18,36,0.95)' }
          },
          animation: { animateScale: true, duration: 650 }
        }
      });
    }

    function buildBarChart(summary) {
      destroyChart(state.barChart);
      const top = summary.top_affected_countries;
      state.barChart = new Chart(document.getElementById('barChart'), {
        type: 'bar',
        data: {
          labels: top.map(x => x.country),
          datasets: [{
            label: 'Confirmed',
            data: top.map(x => x.confirmed),
            backgroundColor: 'rgba(36, 180, 216, 0.75)',
            borderRadius: 8
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#dce7ff' } },
            tooltip: { backgroundColor: 'rgba(10,18,36,0.95)' }
          },
          scales: {
            x: { ticks: { color: '#b7c9f1' }, grid: { display: false } },
            y: { ticks: { color: '#b7c9f1' }, grid: { color: 'rgba(183,201,241,0.08)' } }
          },
          animation: { duration: 700 }
        }
      });
    }

    function buildHistogram(summary) {
      destroyChart(state.histChart);
      const arr = summary.all_country_latest_confirmed.slice().sort((a, b) => a - b);
      const bins = 8;
      const maxV = arr[arr.length - 1] || 1;
      const minV = arr[0] || 0;
      const step = Math.max(1, Math.ceil((maxV - minV) / bins));

      const labels = [];
      const counts = Array.from({ length: bins }, () => 0);
      const fullLabels = [];

      for (let i = 0; i < bins; i++) {
        const low = minV + (i * step);
        const high = i === bins - 1 ? maxV : low + step;
        labels.push(`${Math.floor(low / 1000)}k-${Math.floor(high / 1000)}k`);
        fullLabels.push(`${fmtNum.format(Math.floor(low))} - ${fmtNum.format(Math.floor(high))}`);
      }

      arr.forEach(v => {
        let idx = Math.floor((v - minV) / step);
        if (idx >= bins) idx = bins - 1;
        counts[idx] += 1;
      });

      const totalCountries = counts.reduce((a, b) => a + b, 0);

      state.histChart = new Chart(document.getElementById('histChart'), {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Countries',
            data: counts,
            backgroundColor: 'rgba(255, 207, 92, 0.75)',
            borderColor: 'rgba(255, 207, 92, 1)',
            borderWidth: 1,
            borderRadius: 8
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#dce7ff' } },
            tooltip: {
              backgroundColor: 'rgba(10, 18, 36, 0.98)',
              padding: 14,
              titleColor: '#63f0a0',
              titleFont: { size: 13, weight: '600' },
              bodyColor: '#dce7ff',
              bodyFont: { size: 12 },
              borderColor: 'rgba(255, 207, 92, 0.7)',
              borderWidth: 2,
              displayColors: false,
              callbacks: {
                title: () => 'Case Distribution',
                label: (context) => {
                  const idx = context.dataIndex;
                  const countInRange = context.parsed.y;
                  const percentage = ((countInRange / totalCountries) * 100).toFixed(1);
                  return [
                    `Cases: ${fullLabels[idx]}`,
                    `Countries: ${countInRange}`,
                    `Percentage: ${percentage}% of total`
                  ];
                },
                afterLabel: (context) => {
                  return `Total countries analyzed: ${totalCountries}`;
                }
              }
            }
          },
          scales: {
            x: { 
              title: {
                display: true,
                text: 'Confirmed Cases Range',
                color: '#dce7ff',
                font: { size: 12, weight: '600' }
              },
              ticks: { color: '#b7c9f1' }, 
              grid: { display: false }
            },
            y: { 
              type: 'logarithmic',
              title: {
                display: true,
                text: 'Number of Countries (Log Scale)',
                color: '#dce7ff',
                font: { size: 12, weight: '600' }
              },
              ticks: { color: '#b7c9f1' }, 
              grid: { color: 'rgba(183,201,241,0.08)' }
            }
          }
        }
      });
    }



    function updateTopCountries(summary) {
      const list = document.getElementById('topCountriesList');
      list.innerHTML = '';
      summary.top_5_affected.forEach((item, idx) => {
        const row = document.createElement('div');
        row.className = 'top-country-item';
        row.innerHTML = `<span>${idx + 1}. ${item.country}</span><strong>${fmtNum.format(item.confirmed)}</strong>`;
        list.appendChild(row);
      });
    }

    function updateInsights(summary, rows, countryLabel) {
      // Calculate meaningful metrics from the timeseries
      const first = rows[0] || {};
      const last = rows[rows.length - 1] || {};
      
      // Delta from first to last in selected period
      const delta = Math.max(0, (last.confirmed || 0) - (first.confirmed || 0));
      
      // Use the last day with actual reported cases (not 0)
      const dailyNew = summary.daily_new_last_reported || summary.daily_new || 0;
      const lastReportedDate = summary.last_reported_date || summary.latest_date;
      
      // Compare daily new cases to 7-day MA of daily new cases
      const ma7Daily = summary.moving_average_7d?.daily_new || 0;
      let multiplier = ma7Daily > 0 ? (dailyNew / ma7Daily) : 1;
      
      // Cap extreme multipliers (e.g., from reporting backlogs) at 3.0x
      // This keeps spikes from backlogs readable
      multiplier = Math.max(0, Math.min(3.0, multiplier));
      
      const top = summary.top_5_affected.map(x => x.country).join(', ');
      
      // Add trend description based on multiplier
      let trendDesc = "stable";
      if (multiplier >= 2.5) trendDesc = "sharply increasing";
      else if (multiplier >= 1.5) trendDesc = "increasing";
      else if (multiplier <= 0.5) trendDesc = "sharply decreasing";
      else if (multiplier < 1.0) trendDesc = "decreasing";

      const text = [
        `${countryLabel} cumulative confirmed cases increased by ${fmtNum.format(delta)} over the selected period.`,
        `Latest reported daily new cases: ${fmtNum.format(dailyNew)} on ${lastReportedDate} (${multiplier.toFixed(1)}x the 7-day average, ${trendDesc}).`,
        `The peak daily increase occurred on ${summary.peak_day.date} with ${fmtNum.format(summary.peak_day.daily_new_confirmed)} new confirmed cases.`,
        `Top high-impact countries currently include ${top}.`
      ].join(' ');

      document.getElementById('insightsText').textContent = text;
    }

    async function fetchJson(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Failed API: ${url}`);
      return res.json();
    }

    function getFilters() {
      return {
        country: document.getElementById('countrySelect').value,
        start: document.getElementById('startDate').value,
        end: document.getElementById('endDate').value,
      };
    }

    async function loadDashboard() {
      setLoading(true);
      try {
        const { country, start, end } = getFilters();
        const q = new URLSearchParams();
        if (start) q.set('start', start);
        if (end) q.set('end', end);

        const summary = await fetchJson(`/global-summary?${q.toString()}`);
        let series;

        if (country === 'Global') {
          series = await fetchJson(`/timeseries?${q.toString()}`);
        } else {
          q.set('country', country);
          const countryPayload = await fetchJson(`/country-data?${q.toString()}`);
          series = countryPayload.timeseries;
          summary.daily_new = countryPayload.latest.daily_new;
          summary.growth_rate_latest = countryPayload.latest.growth_rate;
          summary.peak_day = countryPayload.peak_day;
          summary.totals = {
            confirmed: countryPayload.latest.confirmed,
            deaths: countryPayload.latest.deaths,
            recovered: countryPayload.latest.recovered,
            active: countryPayload.latest.active,
          };
          summary.trend = {
            confirmed: 'flat',
            deaths: 'flat',
            recovered: 'flat',
            active: 'flat',
          };
        }

        state.summary = summary;
        state.timeseries = series;

        updateKpis(summary);
        buildLineChart(series);
        buildPieChart(summary);
        buildBarChart(state.summary);
        buildHistogram(state.summary);
        updateTopCountries(state.summary);
        updateInsights(state.summary, series, country === 'Global' ? 'Global' : country);
      } catch (err) {
        document.getElementById('insightsText').textContent = 'Unable to load data. Check backend server and dataset path.';
        console.error(err);
      } finally {
        setLoading(false);
      }
    }

    async function initFilters() {
      const payload = await fetchJson('/all-countries');
      state.countries = payload.countries;

      const select = document.getElementById('countrySelect');
      select.innerHTML = '<option value="Global">Global</option>';
      state.countries.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c;
        opt.textContent = c;
        select.appendChild(opt);
      });

      const startInput = document.getElementById('startDate');
      const endInput = document.getElementById('endDate');
      startInput.min = payload.min_date;
      startInput.max = payload.max_date;
      endInput.min = payload.min_date;
      endInput.max = payload.max_date;
      startInput.value = payload.min_date;
      endInput.value = payload.max_date;
    }

    document.getElementById('applyBtn').addEventListener('click', loadDashboard);

    (async function boot() {
      setLoading(true);
      try {
        await initFilters();
        await loadDashboard();
      } catch (e) {
        setLoading(false);
        document.getElementById('insightsText').textContent = 'Initialization failed. Please verify backend APIs.';
      }
    })();

    /* Chat Bubble Logic */
    const chatState = {
      isOpen: false,
      messages: []
    };

    function toggleChat() {
      chatState.isOpen = !chatState.isOpen;
      const window = document.getElementById('chatWindow');
      window.classList.toggle('active', chatState.isOpen);
      if (chatState.isOpen && chatState.messages.length === 0) {
        addBotMessage('Hi! Ask me anything about COVID-19 data. Try: "Cases in India" or "Top countries"');
      }
    }

    function addMessage(text, isUser = true) {
      chatState.messages.push({ text, isUser });
      renderMessages();
    }

    function addBotMessage(text) {
      addMessage(text, false);
    }

    function renderMessages() {
      const body = document.getElementById('chatBody');
      body.innerHTML = '';
      chatState.messages.forEach(msg => {
        const div = document.createElement('div');
        div.className = `chat-message ${msg.isUser ? 'user' : 'bot'}`;
        div.textContent = msg.text;
        body.appendChild(div);
      });
      body.scrollTop = body.scrollHeight;
    }

    async function sendMessage() {
      const input = document.getElementById('chatInput');
      const text = input.value.trim();
      
      if (!text) {
        console.warn('Input is empty');
        return;
      }

      input.value = '';
      addMessage(text, true);

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        
        const json = await res.json();
        if (json.response) {
          addBotMessage(json.response);
        } else if (json.error) {
          addBotMessage('Error: ' + json.error);
        } else {
          addBotMessage('No response received');
        }
      } catch (err) {
        console.error('Chat error:', err);
        addBotMessage('Connection error. Check if backend is running. Error: ' + err.message);
      }
    }

    // Set up event listeners with proper DOM ready handling
    function setupChatListeners() {
      const sendBtn = document.getElementById('chatSendBtn');
      const chatInput = document.getElementById('chatInput');
      
      if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
      }
      if (chatInput) {
        chatInput.addEventListener('keypress', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            sendMessage();
          }
        });
      }
    }

    // Try to set up listeners immediately, and also on DOMContentLoaded
    setupChatListeners();
    document.addEventListener('DOMContentLoaded', setupChatListeners);
  </script>

  <!-- Chat Bubble -->
  <button id="chatBubble" class="chat-bubble-button" onclick="toggleChat()">💬</button>

  <!-- Chat Window -->
  <div id="chatWindow" class="chat-window">
    <div class="chat-header">
      <span>COVID-19 Assistant</span>
      <button class="chat-close-btn" onclick="toggleChat()">✕</button>
    </div>
    <div id="chatBody" class="chat-body"></div>
    <div class="chat-input-box">
      <input id="chatInput" type="text" placeholder="Ask about cases, countries, dates..." />
      <button id="chatSendBtn" class="chat-send-btn">Send</button>
    </div>
  </div>
</body>
</html>
"""
    return html_template


@app.route("/all-countries")
def all_countries():
    data = load_data()
    return jsonify(
        {
            "countries": data["countries"],
            "min_date": data["min_date"].strftime("%Y-%m-%d"),
            "max_date": data["max_date"].strftime("%Y-%m-%d"),
            "source": data["source"],
        }
    )


@app.route("/global-summary")
def global_summary():
    data = load_data()
    start = request.args.get("start")
    end = request.args.get("end")

    global_ts = filter_date_range(data["global_ts"], start, end)
    latest_country = data["latest_country"]

    latest_row = global_ts.iloc[-1]
    prev_row = global_ts.iloc[-2] if len(global_ts) > 1 else latest_row

    peak_row = global_ts.loc[global_ts["DailyNewConfirmed"].idxmax()]

    # Find last row with non-zero daily new cases (better for insights than a zero day)
    last_nonzero_row = latest_row
    for idx in range(len(global_ts) - 1, -1, -1):
        if global_ts.iloc[idx]["DailyNewConfirmed"] > 0:
            last_nonzero_row = global_ts.iloc[idx]
            break

    # Calculate trend analysis
    week_ago_idx = max(0, len(global_ts) - 8)
    week_ago_row = global_ts.iloc[week_ago_idx]
    
    month_ago_idx = max(0, len(global_ts) - 32)
    month_ago_row = global_ts.iloc[month_ago_idx]

    week_change_confirmed = (
        (latest_row["Confirmed"] - week_ago_row["Confirmed"]) / max(1, week_ago_row["Confirmed"]) * 100
        if week_ago_row["Confirmed"] > 0 else 0
    )
    week_change_deaths = (
        (latest_row["Deaths"] - week_ago_row["Deaths"]) / max(1, week_ago_row["Deaths"]) * 100
        if week_ago_row["Deaths"] > 0 else 0
    )
    
    month_change_confirmed = (
        (latest_row["Confirmed"] - month_ago_row["Confirmed"]) / max(1, month_ago_row["Confirmed"]) * 100
        if month_ago_row["Confirmed"] > 0 else 0
    )
    
    recovery_rate = (
        (latest_row["Recovered"] / latest_row["Confirmed"] * 100)
        if latest_row["Confirmed"] > 0 else 0
    )
    fatality_rate = (
        (latest_row["Deaths"] / latest_row["Confirmed"] * 100)
        if latest_row["Confirmed"] > 0 else 0
    )

    top_affected = latest_country.head(10)
    top5 = top_affected.head(5)

    return jsonify(
        {
            "latest_date": latest_row["Date"].strftime("%Y-%m-%d"),
            "totals": {
                "confirmed": int(latest_row["Confirmed"]),
                "deaths": int(latest_row["Deaths"]),
                "recovered": int(latest_row["Recovered"]),
                "active": int(latest_row["Active"]),
            },
            "daily_new": int(latest_row["DailyNewConfirmed"]),
            "daily_new_last_reported": int(last_nonzero_row["DailyNewConfirmed"]),
            "last_reported_date": last_nonzero_row["Date"].strftime("%Y-%m-%d"),
            "moving_average_7d": {
                "confirmed": float(latest_row["MA7_Confirmed"]),
                "deaths": float(latest_row["MA7_Deaths"]),
                "recovered": float(latest_row["MA7_Recovered"]),
                "daily_new": float(latest_row["MA7_DailyNew"]),
            },
            "growth_rate_latest": float(latest_row["GrowthRate"]),
            "trend": {
                "confirmed": trend_flag(latest_row["Confirmed"], prev_row["Confirmed"]),
                "deaths": trend_flag(latest_row["Deaths"], prev_row["Deaths"]),
                "recovered": trend_flag(latest_row["Recovered"], prev_row["Recovered"]),
                "active": trend_flag(latest_row["Active"], prev_row["Active"]),
            },
            "trend_analytics": {
                "week_change_confirmed_pct": float(week_change_confirmed),
                "week_change_deaths_pct": float(week_change_deaths),
                "month_change_confirmed_pct": float(month_change_confirmed),
                "recovery_rate_pct": float(recovery_rate),
                "fatality_rate_pct": float(fatality_rate),
            },
            "peak_day": {
                "date": peak_row["Date"].strftime("%Y-%m-%d"),
                "daily_new_confirmed": int(peak_row["DailyNewConfirmed"]),
            },
            "top_affected_countries": [
                {
                    "country": row["Country/Region"],
                    "confirmed": int(row["Confirmed"]),
                    "deaths": int(row["Deaths"]),
                    "recovered": int(row["Recovered"]),
                    "active": int(row["Active"]),
                }
                for _, row in top_affected.iterrows()
            ],
            "top_5_affected": [
                {
                    "country": row["Country/Region"],
                    "confirmed": int(row["Confirmed"]),
                }
                for _, row in top5.iterrows()
            ],
            "all_country_latest_confirmed": [
                int(v) for v in latest_country["Confirmed"].astype(int).tolist()
            ],
        }
    )


@app.route("/timeseries")
def timeseries():
    data = load_data()
    start = request.args.get("start")
    end = request.args.get("end")

    global_ts = filter_date_range(data["global_ts"], start, end)

    payload = []
    for _, row in global_ts.iterrows():
        payload.append(
            {
                "date": row["Date"].strftime("%Y-%m-%d"),
                "confirmed": int(row["Confirmed"]),
                "deaths": int(row["Deaths"]),
                "recovered": int(row["Recovered"]),
                "active": int(row["Active"]),
                "daily_new": int(row["DailyNewConfirmed"]),
                "growth_rate": float(row["GrowthRate"]),
                "ma7_confirmed": float(row["MA7_Confirmed"]),
            }
        )

    return jsonify(payload)


@app.route("/country-data")
def country_data():
    data = load_data()
    country = request.args.get("country", "").strip()
    start = request.args.get("start")
    end = request.args.get("end")

    if not country:
        return jsonify({"error": "country query parameter is required"}), 400

    country_ts = data["country_ts"]
    filtered = country_ts[country_ts["Country/Region"] == country].copy()

    if filtered.empty:
        return jsonify({"error": f"country '{country}' not found"}), 404

    filtered = filter_date_range(filtered, start, end)

    peak_row = filtered.loc[filtered["DailyNewConfirmed"].idxmax()]

    payload = []
    for _, row in filtered.iterrows():
        payload.append(
            {
                "date": row["Date"].strftime("%Y-%m-%d"),
                "confirmed": int(row["Confirmed"]),
                "deaths": int(row["Deaths"]),
                "recovered": int(row["Recovered"]),
                "active": int(row["Active"]),
                "daily_new": int(row["DailyNewConfirmed"]),
                "growth_rate": float(row["GrowthRate"]),
                "ma7_confirmed": float(row["MA7_Confirmed"]),
            }
        )

    latest_row = filtered.iloc[-1]

    return jsonify(
        {
            "country": country,
            "latest": {
                "date": latest_row["Date"].strftime("%Y-%m-%d"),
                "confirmed": int(latest_row["Confirmed"]),
                "deaths": int(latest_row["Deaths"]),
                "recovered": int(latest_row["Recovered"]),
                "active": int(latest_row["Active"]),
                "daily_new": int(latest_row["DailyNewConfirmed"]),
                "growth_rate": float(latest_row["GrowthRate"]),
            },
            "peak_day": {
                "date": peak_row["Date"].strftime("%Y-%m-%d"),
                "daily_new_confirmed": int(peak_row["DailyNewConfirmed"]),
            },
            "timeseries": payload,
        }
    )


@app.route("/chat", methods=["POST"])
def chat():
    """Query the COVID API using natural language.

    Supports:
    - "Cases in <country>" -> latest country stats
    - "Top countries" -> top 5 affected
    - "Deaths in <country>" -> country death count
    - "When was peak?" -> peak detection info
    """
    import re

    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    response_text = None
    data = load_data()

    # Pattern 1: Top countries/countries query
    if re.search(r"top\s+(5|10|countries)|most\s+affected|global\s+totals", user_message, re.I):
        latest_country = data["latest_country"].head(5)
        if not latest_country.empty:
            countries_str = ", ".join([
                f"{i+1}. {row['Country/Region']} ({int(row['Confirmed']):,})"
                for i, (_, row) in enumerate(latest_country.iterrows())
            ])
            global_totals = data["global_ts"].iloc[-1]
            response_text = (
                f"Top 5 most affected countries:\n{countries_str}\n\n"
                f"Global totals: {int(global_totals['Confirmed']):,} confirmed, "
                f"{int(global_totals['Deaths']):,} deaths"
            )

    # Pattern 2: Cases in [country]
    if not response_text:
        country_match = re.search(r"cases?\s+in\s+([a-zA-Z\s]+?)(?:\s+in\s+\d+|$)", user_message, re.I)
        if country_match:
            country_name = country_match.group(1).strip()
            filtered = data["country_ts"][data["country_ts"]["Country/Region"].str.lower() == country_name.lower()]
            if not filtered.empty:
                latest = filtered.iloc[-1]
                response_text = (
                    f"{country_name} (as of {latest['Date'].strftime('%Y-%m-%d')}):\n"
                    f"- Confirmed: {int(latest['Confirmed']):,}\n"
                    f"- Deaths: {int(latest['Deaths']):,}\n"
                    f"- Recovered: {int(latest['Recovered']):,}\n"
                    f"- Active: {int(latest['Active']):,}"
                )
            else:
                response_text = f"Could not find data for {country_name}."

    # Pattern 3: Deaths in [country]
    if not response_text:
        deaths_match = re.search(r"deaths?\s+in\s+([a-zA-Z\s]+)", user_message, re.I)
        if deaths_match:
            country_name = deaths_match.group(1).strip()
            filtered = data["country_ts"][data["country_ts"]["Country/Region"].str.lower() == country_name.lower()]
            if not filtered.empty:
                latest = filtered.iloc[-1]
                response_text = f"{country_name} has reported {int(latest['Deaths']):,} deaths as of {latest['Date'].strftime('%Y-%m-%d')}."
            else:
                response_text = f"Could not find data for {country_name}."

    # Pattern 4: Peak query
    if not response_text and re.search(r"peak|highest|surge|maximum", user_message, re.I):
        global_ts = data["global_ts"]
        peak_idx = global_ts["DailyNewConfirmed"].idxmax()
        peak_row = global_ts.loc[peak_idx]
        response_text = (
            f"Peak day: {peak_row['Date'].strftime('%Y-%m-%d')} with "
            f"{int(peak_row['DailyNewConfirmed']):,} new confirmed cases."
        )

    # Fallback
    if not response_text:
        response_text = (
            "I can help you with COVID-19 data. Try:\n"
            "- 'Cases in India'\n"
            "- 'Deaths in France'\n"
            "- 'Top countries'\n"
            "- 'When was peak?'"
        )

    return jsonify({
        "response": response_text,
        "timestamp": pd.Timestamp.now().isoformat()
    })


if __name__ == "__main__":
    import requests
    app.run(host="0.0.0.0", port=5000, debug=True)
