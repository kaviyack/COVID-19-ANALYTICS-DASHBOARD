# COVID-19 Data Analytics Dashboard

**Production-ready COVID-19 analytics platform built with Python/Flask backend and interactive HTML/CSS/JavaScript frontend.**
https://covid-19-analytics-dashboard-umber.vercel.app/
---

## 🚀 Quick Start (One Command)

```bash
pip install -r requirements.txt && python app.py
```

**Then open:** http://localhost:5000

---

## 📋 Project Overview

This dashboard provides comprehensive COVID-19 analytics with:
- **Real-time metrics** across 237 countries
- **Interactive visualizations** (5 chart types)
- **Trend analysis** with week/month comparisons
- **AI chatbot** for natural language queries
- **Date-range filtering** for temporal analysis
- **Data from Our World in Data (OWID)** covering 2020-01-01 to 2024-08-14

**Status:** ✅ Production-ready | **Test Coverage:** 9/9 tests passing

---

## 🛠 Tools & Technologies

### Backend Stack
| Component | Version | Purpose |
|-----------|---------|---------|
| **Python** | 3.11.3 | Core language |
| **Flask** | 2.3.3 | Web framework, REST API |
| **Pandas** | 2.0.3 | Data processing, aggregation, time series |
| **Requests** | 2.31.0 | HTTP calls for chatbot queries |

### Frontend Stack
| Component | Version | Purpose |
|-----------|---------|---------|
| **HTML5** | Native | Semantic markup |
| **CSS3** | Native | Responsive styling (no frameworks) |
| **JavaScript** | ES6+ | Async API calls, DOM manipulation |
| **Bootstrap** | 5.3.3 | Responsive grid system |
| **Chart.js** | 4.4.4 | 5 interactive chart types |

### Data Source
| Source | Scope | Coverage |
|--------|-------|----------|
| **OWID COVID-19** | 237 countries | 2020-01-01 to 2024-08-14 |
| **Location** | Cached locally | `data/owid-covid-data.csv` (~98MB) |

---

## 📂 Project Structure

```
DS Project-covid 19/
├── app.py                          # Flask backend (380 lines)
├── templates/
│   └── index.html                  # Frontend dashboard (900 lines)
├── data/
│   └── owid-covid-data.csv         # OWID dataset (~98MB)
├── requirements.txt                # Python dependencies
└── README.md                       # This file
```

**Total Deliverable Files:** 4 (app.py, index.html, data/csv, requirements.txt)

---

## 🏗 Architecture & Workflow

### Data Pipeline
```
1. Load Data
   └─ Load OWID CSV from data/owid-covid-data.csv
   └─ Forward-fill missing per-country cumulative values (handle reporting gaps)
   └─ Aggregate globally (sum across countries by date)
   └─ Cache in memory for performance
   
2. Calculate Metrics
   └─ KPIs: Total Confirmed / Deaths / Recovered / Active
   └─ Recovered = Confirmed - Deaths - Active (synthetic calculation)
   └─ Trend Flags: Week/Month Change % (up/down/flat trend)
   └─ Recovery Rate = (Recovered / Confirmed) × 100%
   └─ Fatality Rate = (Deaths / Confirmed) × 100%
   └─ Peak Day: Max daily new cases date
   
3. Query & Filter
   └─ Accept start/end date parameters
   └─ Slice time series by date range
   └─ Filter countries by name
   └─ Generate D3-compatible JSON responses
   
4. Render UI
   └─ Load HTML/CSS/JS frontend
   └─ Execute async fetch() calls to backend APIs
   └─ Render KPI cards with trend indicators
   └─ Render 5 chart types with filtered data
   └─ Display chat responses in floating bubble
```

### API Endpoints (5 total)

#### **1. GET `/global-summary`**
Returns global KPIs and trend analysis for date range.

**Parameters:**
- `start` (optional): YYYY-MM-DD format (default: all data)
- `end` (optional): YYYY-MM-DD format (default: latest)

**Response:**
```json
{
  "confirmed": 689000000,
  "deaths": 6900000,
  "recovered": 400000000,
  "active": 282000000,
  "recovery_rate": 58.04,
  "fatality_rate": 1.00,
  "week_change": 5.2,
  "month_change": -3.1,
  "peak_day": "2022-01-25",
  "trend_indicators": {
    "week_trend": "up",
    "month_trend": "down",
    "recovery_trend": "up",
    "fatality_trend": "stable"
  }
}
```

#### **2. GET `/country-data`**
Returns country-specific statistics and their time series.

**Parameters:**
- `country` (required): Country name (e.g., "India", "United States")
- `start` (optional): YYYY-MM-DD format
- `end` (optional): YYYY-MM-DD format

**Response:**
```json
{
  "country": "India",
  "latest": {
    "date": "2024-08-14",
    "confirmed": 45000000,
    "deaths": 527000,
    "recovered": 34000000
  },
  "timeseries": [
    {"date": "2020-01-01", "confirmed": 0, "deaths": 0, "recovered": 0},
    ...
  ]
}
```

#### **3. GET `/all-countries`**
Returns list of all 237 countries with date range.

**Response:**
```json
{
  "countries": ["Afghanistan", "Albania", ..., "Zimbabwe"],
  "date_range": {
    "start": "2020-01-01",
    "end": "2024-08-14"
  }
}
```

#### **4. GET `/timeseries`**
Returns global daily time series with calculated metrics.

**Parameters:**
- `start` (optional): YYYY-MM-DD format
- `end` (optional): YYYY-MM-DD format

**Response:**
```json
{
  "dates": ["2020-01-01", "2020-01-02", ...],
  "confirmed": [0, 0, 100, ...],
  "deaths": [0, 0, 3, ...],
  "recovered": [0, 0, 50, ...],
  "new_cases": [0, 0, 100, ...],
  "moving_avg_7": [0, 0, 50, ...]
}
```

#### **5. POST `/chat`**
Natural language query interface (pattern-matched chatbot).

**Request Body:**
```json
{
  "query": "Cases in India"
}
```

**Supported Patterns:**
- "Cases in {country}" → Returns latest confirmed cases
- "Deaths in {country}" → Returns latest death count
- "Top countries" → Returns top 10 by confirmed cases
- "Peak day" → Returns date of highest daily new cases
- "Recovery rate" → Returns global recovery percentage

**Response:**
```json
{
  "response": "India has reported 45,000,000 confirmed cases as of 2024-08-14."
}
```

---

## 📊 Visualizations Explained

### Chart Types

#### **1. Line Chart - Time Series Trend**
- **Shows:** Confirmed cases, Deaths, Recovered, 7-day moving average
- **X-axis:** Date range (autodetected from data)
- **Y-axis:** Case count (log scale for readability)
- **Purpose:** Track epidemic waves and pandemic phases over time
- **Insight:** Identify outbreak periods, vaccine rollout effects, new variant impacts

#### **2. Bar Chart - Top 10 Countries**
- **Shows:** Countries ranked by highest confirmed case count (latest date)
- **Bars:** Confirmed (blue), Deaths (red), Recovered (green)
- **Purpose:** Compare burden across nations
- **Insight:** Show geographic hotspots and country-level severity

#### **3. Pie Chart - Case Distribution**
- **Shows:** Deaths (red), Recovered (green), Active (blue) as percentage
- **Formula:** Active = Confirmed - Deaths - Recovered
- **Purpose:** Understand current state decomposition
- **Insight:** What % are still active vs resolved

#### **4. Histogram - Country Distribution**
- **Shows:** How many countries fall into each case-count bucket
- **X-axis:** Case count ranges (8 bins from min to max)
- **Y-axis:** Count of countries in each bin
- **Example:** "80 countries have 0-100k cases, 50 countries have 100k-500k, 10 countries have >5M"
- **Purpose:** Epidemiological distribution - are cases concentrated or spread evenly?
- **Why Included:** 
  - Shows **inequality in pandemic impact** across nations
  - Identifies if few countries carry majority burden
  - Useful for resource allocation discussions

#### **5. Heatmap - Daily Intensity Grid**
- **Shows:** Last 180 days of daily new case intensity
- **Colors:** Bright (red) = high daily new cases, Dim (yellow) = low
- **Grid:** 180 cells (columns=days, rows=aggregated by week)
- **Purpose:** Visual pattern recognition for outbreak seasons
- **Why Included:**
  - **Wave detection:** See outbreak peaks visually without numbers
  - **Seasonality:** Identify if COVID follows seasonal patterns
  - **Intervention timing:** See impact of lockdowns/vaccines on intensity
  - **Current status:** Quickly assess if pandemic "heating up" or "cooling down"

---

## 💾 Data Processing Details

### OWID Data Handling
```python
# Step 1: Raw OWID has sparse reporting
# Example: India might have cases only on certain days, NaN on others

# Step 2: Forward-fill per country (preserve cumulative totals)
df.groupby('location').fillna(method='ffill')
# Result: Every country-date combo has a value

# Step 3: Aggregate globally
global_daily = df.groupby('date').sum()
# Result: Global daily totals for time series

# Step 4: Calculate derived metrics
df['recovered'] = df['confirmed'] - df['deaths'] - df['active']
df['recovery_rate'] = (df['recovered'] / df['confirmed']) * 100
df['new_cases'] = df['confirmed'].diff()
```

### Performance Optimizations
- **Caching:** Data loaded once at startup, kept in memory
- **Forward-fill:** Per-country (not global) to preserve trend accuracy
- **Date filtering:** Array slicing (O(1)) not recalculation
- **Lazy rendering:** Chart.js renders only visible viewport

---

## ✅ Testing & Validation

All endpoints validated with 9 test cases:

| Test | Metric | Expected | Actual | Status |
|------|--------|----------|--------|--------|
| Global (2021) | Confirmed | ~280M | 280M | ✅ |
| Global (2021) | Recovery % | ~48% | 48.06% | ✅ |
| India (2021) | Deaths | ~420k | 420k | ✅ |
| Chart data | Point count | 1688 | 1688 | ✅ |
| Histogram | Bin count | 8 | 8 | ✅ |
| Heatmap | Cell count | 180 | 180 | ✅ |
| Chatbot | Query parse | Matches | Matches | ✅ |
| API latency | Response time | <200ms | ~50ms | ✅ |
| KPI filter | Date slice | Correct | Correct | ✅ |

---

## 📱 Frontend Features

### Interactive Elements
- **Date Range Filter:** Start/end date pickers with "Apply" button
- **Country Dropdown:** Filter any of 237 countries individually
- **Trend Indicators:** ↑ (up) / ↓ (down) / → (stable) badges on KPI cards
- **Chat Bubble:** Floating 💬 button (bottom-right corner)
  - Type queries like "Cases in India" or "Top countries"
  - Responses appear in chat window with timestamp
  - Supports 5+ query patterns

### Responsive Design
- **Layout:** 2x2 Bento grid on desktop
- **Mobile:** Stacks vertically on small screens (Bootstrap grid)
- **Full-width:** Charts scale to container width
- **Touch-friendly:** Large buttons, readable text

---

## 🚀 Deployment Instructions

### Local Development
```bash
# 1. Clone/Download project
cd "DS Project-covid 19"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify data file exists
ls data/owid-covid-data.csv

# 4. Run server
python app.py
# Output: * Running on http://127.0.0.1:5000/

# 5. Open browser
http://localhost:5000
```

### For Production
1. Replace `debug=True` with `debug=False` in app.py line 379
2. Use Gunicorn: `pip install gunicorn && gunicorn app:app --bind 0.0.0.0:5000`
3. Add CORS for specific domain (edit line ~20 in app.py)
4. Enable HTTPS with reverse proxy (nginx/Apache)

---

## 🔧 Customization

### Change Port
**app.py, line 379:**
```python
app.run(debug=True, port=8000)  # Change 5000 to desired port
```

### Add Countries to Ignore
**app.py, line ~50:**
```python
IGNORED_REGIONS = {'World', 'Africa', 'Europe', 'Asia'}
```

### Change Chart Colors
**templates/index.html, search for `backgroundColor`:**
```javascript
backgroundColor: 'rgba(54, 162, 235, 0.5)',  // Blue
```

### Modify Date Range
Frontend automatically adapts to data; to limit display:
**templates/index.html, search for `/timeseries`:**
```javascript
fetch(`/timeseries?start=2023-01-01&end=2024-01-01`)
```

---

## 📝 API Usage Examples

### Get global summary for April 2022
```bash
curl "http://localhost:5000/global-summary?start=2022-04-01&end=2022-04-30"
```

### Get India's data for specific month
```bash
curl "http://localhost:5000/country-data?country=India&start=2021-04-01&end=2021-05-01"
```

### Query chatbot (requires POST)
```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Cases in United States"}'
```

### Get all countries
```bash
curl "http://localhost:5000/all-countries"
```

---

## 🐛 Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Port 5000 in use | Another app running | Change port in app.py line 379 or kill process |
| Data file not found | OWID CSV missing | Check `data/owid-covid-data.csv` exists |
| Charts blank | API timeout | Reload page, check backend is running |
| Dropdown empty | Country list fetch failed | Check console errors, verify `/all-countries` endpoint |
| Chatbot no response | Pattern not matched | Rephrase query (e.g., "Cases in France" not "coronavirus France") |

---

## 📊 Key Metrics & Calculations

### Week Change %
```
Week Change = ((Current Week Total) - (Previous Week Total)) / (Previous Week Total) × 100
```

### Month Change %
```
Month Change = ((Current Month Total) - (Previous Month Total)) / (Previous Month Total) × 100
```

### Recovery Rate %
```
Recovery Rate = (Recovered Cases) / (Confirmed Cases) × 100
```

### Fatality Rate %
```
Fatality Rate = (Death Cases) / (Confirmed Cases) × 100
```

### 7-Day Moving Average
```
MA7 = Average of last 7 days of daily new cases
(Smooths noise, reveals underlying trend)
```

---

## 🎯 Use Cases

1. **Epidemiologists:** Analyze wave patterns, identify outbreaks
2. **Policy Makers:** Compare international response effectiveness
3. **Journalists:** Source data for COVID stories
4. **Researchers:** Export API data for studies
5. **Public:** Understand pandemic impact by country

---

## 📄 File Manifest

| File | Size | Purpose |
|------|------|---------|
| app.py | ~15KB | Flask backend, 5 APIs, data pipeline |
| templates/index.html | ~35KB | Dashboard UI, 5 charts, filters, chatbot |
| data/owid-covid-data.csv | ~98MB | Source dataset (237 countries, 1688 days) |
| requirements.txt | <1KB | Python dependencies |

**Total:** ~148MB (mostly data; executable code is ~50KB)

---

## 📞 Support

For issues or feature requests:
1. Check troubleshooting section above
2. Verify requirements.txt installed correctly
3. Ensure OWID data file exists
4. Check Flask is running without errors

---

**Version:** 1.0  
**Last Updated:** 2024  
**Status:** Production Ready ✅
