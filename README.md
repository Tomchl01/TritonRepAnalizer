# 🧠 TritonRepAnalizer

An automated YouTube analysis pipeline built for the Triton Poker series.  
It fetches videos, analyzes hand histories, summarizes key moments, and publishes visual reports to GitHub Pages.

### 🔗 Live Report
👉 [View the latest HTML report](https://tomchl01.github.io/TritonRepAnalizer/)

---

## 🔍 What It Does

1. **Fetches recent videos** from a specified YouTube playlist using the YouTube API.
2. **Downloads and structures transcripts**.
3. **Analyzes the content** using local AI models (e.g., Mixtral via Ollama).
4. **Extracts insights** including:
   - Summary of the video
   - Key hands and timestamps
   - Notable players
   - Winner information
5. **Generates an HTML report** using Jinja2 templates.
6. **Publishes the report** to GitHub Pages.

---

## 📂 Project Structure

TritonRepAnalizer/ ├── HTMLGENERATOR.py # Generates the HTML report ├── YTFETCHER.py # (or similar) Fetches videos & transcripts ├── ANALYZER.py # Uses AI to extract insights ├── data/ │ ├── summaries/ # Stores JSON summaries per video │ └── reports/ # Stores generated HTML reports ├── templates/ │ └── report_template.html # Jinja2 HTML template ├── .env # API keys and secrets (excluded from Git) └── index.html # Latest report for GitHub Pages


---

## ⚙️ Tech Stack

- Python 3.11
- YouTube Data API v3
- OpenAI / Mixtral (via Ollama or LM Studio)
- Jinja2 for templating
- GitHub Actions (optional for deployment)
- GitHub Pages (for live report)

---

## 🔒 Security

All `.env` and credential files are excluded via `.gitignore`.  
The history has been rewritten to remove previously leaked tokens.  
GitHub Push Protection is active.

---

## 🚀 How to Run It Locally

1. Clone the repo  
2. Add a `.env` file with your API keys:
   ```env
   YOUTUBE_API_KEY=your-key
   GITHUB_TOKEN=your-token
   REPO_NAME=Tomchl01/TritonRepAnalizer
python HTMLGENERATOR.py
