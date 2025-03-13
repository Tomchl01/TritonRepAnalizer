

import os
import json
import logging
import re
import requests
import isodate
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from datetime import datetime
from tqdm import tqdm
from bs4 import BeautifulSoup
from github import Github
import base64

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler("html_report_generator.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Paths
SUMMARY_PATH = "data/summaries/"
REPORTS_PATH = "data/reports/"
TEMPLATE_DIR = "templates/"
TEMPLATE_FILE = "report_template.html"

# GitHub Configuration
GITHUB_TOKEN = "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"  # Hardcoded token for testing
REPO_NAME = "Tomchl01/TritonRepAnalizer"
HTML_FILE_PATH = "index.html"

# Ensure report directory exists
os.makedirs(REPORTS_PATH, exist_ok=True)

# Load Jinja2 Environment
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# YouTube API Configuration
YOUTUBE_API_KEY = "AIzaSyDNomTIlROwsthvX3NqbBNwQ4-hz14c_jA" #Replace with your youtube api key
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"

# Utility to format video duration
def format_duration(iso_duration):
    try:
        duration = isodate.parse_duration(iso_duration)
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    except Exception:
        return "Unknown Duration"

# Clean text by removing unwanted characters
def clean_text(text):
    text = re.sub(r'[\*#]', '', text)  # Remove Markdown symbols
    text = re.sub(r'(\s\-\s)', ' - ', text)  # Clean bullet points
    return text.strip()

# Improved Timestamp Conversion Utility
def ensure_clickable_timestamps(text, video_id):
    timestamp_pattern = re.compile(r"\[(\d{1,3}(?:\.\d{2})?)\]|\[(\d{1,3}:\d{2}(?::\d{2})?)\]")
    
    def format_timestamp(match):
        # Handle timestamps like [10.88]
        if match.group(1):
            minutes = int(float(match.group(1)))
            seconds = int((float(match.group(1)) - minutes) * 60)
            formatted_time = f"{minutes:02}:{seconds:02}"
            seconds_value = minutes * 60 + seconds
        else:
            # Handle timestamps like [1:22:18]
            formatted_time = match.group(2)
            seconds_value = convert_to_seconds(formatted_time)

        return f"<a href='https://www.youtube.com/watch?v={video_id}&t={seconds_value}' target='_blank' class='highlighted-timestamp'>[{formatted_time}]</a>"

    return timestamp_pattern.sub(format_timestamp, text)

def convert_to_seconds(timestamp):
    parts = list(map(int, timestamp.split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0

# Format summaries with clickable timestamps and collapsible details
def format_summary(summary_text, video_id):
    lines = summary_text.strip().split('\n')
    formatted_summary = ""
    is_collapsible = False

    for line in lines:
        line = clean_text(line)
        if not line.strip():
            continue

        if any(keyword in line for keyword in [
            "Key Poker Moments", 
            "Momentum Shifts", 
            "Standout Players", 
            "Strategic Insights"
        ]):
            if is_collapsible:
                formatted_summary += "</div>"
            formatted_summary += f"<div class='collapsible'><div class='collapsible-header'>{line.strip()}</div><div class='collapsible-content'>"
            is_collapsible = True
        else:
            line = ensure_clickable_timestamps(line, video_id)
            formatted_summary += f"<li>{line}</li>"

    if is_collapsible:
        formatted_summary += "</div>"

    return f"<ul class='summary-list'>{formatted_summary}</ul>"

# Load the template
def load_template():
    try:
        return env.get_template(TEMPLATE_FILE)
    except TemplateNotFound:
        logging.error(f"❌ Template file '{TEMPLATE_FILE}' not found in '{TEMPLATE_DIR}'")
        exit(1)

# Load summaries
def load_summaries():
    summaries = []
    for filename in os.listdir(SUMMARY_PATH):
        if filename.endswith(".json"):
            with open(os.path.join(SUMMARY_PATH, filename), 'r', encoding='utf-8') as file:
                try:
                    data = json.load(file)
                    summaries.append(data)
                except json.JSONDecodeError as e:
                    logging.warning(f"⚠️ Skipping {filename} due to decoding error: {e}")
    return summaries

# Fetch video details from YouTube API with retries
def fetch_video_details(video_id):
    retries = 3
    for attempt in range(retries):
        try:
            response = requests.get(YOUTUBE_API_URL, params={
                'part': 'snippet,contentDetails',
                'id': video_id,
                'key': YOUTUBE_API_KEY
            })
            data = response.json()
            if 'items' in data and len(data['items']) > 0:
                item = data['items'][0]
                title = item['snippet']['title']
                duration = format_duration(item['contentDetails']['duration'])
                upload_date = item['snippet']['publishedAt']
                return title, duration, upload_date
            else:
                logging.warning(f"⚠️ No details found for video ID: {video_id}. Response: {data}")
                return "Unknown Title", "Unknown Duration", "Unknown Date"
        except requests.RequestException as e:
            logging.error(f"❌ Error fetching video details (attempt {attempt + 1}/{retries}): {e}")
            time.sleep(2 ** attempt)  # Exponential backoff
    return "Unknown Title", "Unknown Duration", "Unknown Date"

# Generate the final HTML report
def generate_html_report(summaries):
    video_entries = []
    invalid_video_entries = []

    for summary in summaries:
        video_id = summary.get("video_id", "Unknown ID")
        title, duration, upload_date = fetch_video_details(video_id)
        
        if upload_date == "Unknown Date":
            formatted_date = "Unknown Date"
            invalid_video_entries.append(video_id)
        else:
            try:
                formatted_date = datetime.strptime(upload_date, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y %B %d')
            except ValueError:
                logging.warning(f"⚠️ Invalid date format for video ID: {video_id}")
                formatted_date = "Unknown Date"
                invalid_video_entries.append(video_id)
        
        entries_html = ""
        for chunk in summary.get("summaries", []):
            chunk_summary = chunk.get("summary", "No content available.")
            entries_html += format_summary(chunk_summary, video_id)

        video_entries.append({
            'html': f'''
                <div class="video-entry" id="{video_id}">
                    <h3 class="video-title">{title}</h3>
                    <p class="video-details">Duration: {duration} | Uploaded: {formatted_date}</p>
                    <div class="video-preview">
                        <iframe src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>
                    </div>
                    {entries_html}
                </div>
            ''',
            'upload_date': upload_date
        })

    # Sort video entries by upload date (most recent first)
    video_entries.sort(key=lambda x: x.get('upload_date', 'Unknown Date'), reverse=True)

    rendered_html = load_template().render(
        video_entries="".join(entry['html'] for entry in video_entries),
        invalid_video_entries=invalid_video_entries
    )

    report_path = os.path.join(REPORTS_PATH, "latest_report.html")

    with open(report_path, 'w', encoding='utf-8') as report_file:
        report_file.write(rendered_html)

    logging.info(f"✅ Report updated successfully: {report_path}")
    return report_path

# Update HTML file in GitHub repository
def update_github_html(html_content):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    contents = repo.get_contents(HTML_FILE_PATH)
    commit_message = f"Automated update of {HTML_FILE_PATH} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
    repo.update_file(contents.path, commit_message, html_content, contents.sha)
    logging.info(f"✅ HTML file updated successfully in GitHub repository: {HTML_FILE_PATH}")

# Main execution
def main():
    logging.info("🚀 Starting Report Generator...")
    summaries = load_summaries()
    logging.info(f"📝 Collected {len(summaries)} summaries.")

    if not summaries:
        logging.warning("⚠️ No summaries found. Report will be empty.")

    report_path = generate_html_report(summaries)

    with open(report_path, 'r', encoding='utf-8') as file:
        html_content = file.read()

    update_github_html(html_content)

if __name__ == "__main__":
    main()