import os
import json
import logging
import re
import requests
import isodate
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from github import Github
from googleapiclient.discovery import build
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration (Environment Variables)
SUMMARY_PATH = os.getenv("SUMMARY_PATH", "./data/summaries")
REPORTS_PATH = os.getenv("REPORTS_PATH", "./data/reports")
TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "./templates")
TEMPLATE_FILE = os.getenv("TEMPLATE_FILE", "report_template.html")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
REPO_NAME = os.getenv("REPO_NAME", "Tomchl01/TritonRepAnalizer")
HTML_FILE_PATH = os.getenv("HTML_FILE_PATH", "index.html")
CURRENT_USER = os.getenv("CURRENT_USER", "Tomchl01")

# Automatically capture the current timestamp
CURRENT_TIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Ensure directories exist
for path in [SUMMARY_PATH, REPORTS_PATH, TEMPLATE_DIR]:
    os.makedirs(path, exist_ok=True)

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler("triton_analyzer.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Initialize APIs
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def get_video_details(video_id: str) -> Optional[Dict]:
    """Fetch video details from YouTube API"""
    try:
        request = youtube.videos().list(
            part="snippet,contentDetails",
            id=video_id
        )
        response = request.execute()

        if not response['items']:
            logging.warning(f"No video details found for ID: {video_id}")
            return None

        video = response['items'][0]
        snippet = video['snippet']
        duration = isodate.parse_duration(video['contentDetails']['duration'])
        
        return {
            'title': snippet['title'],
            'duration': f"{int(duration.total_seconds() // 3600):02d}:{int((duration.total_seconds() % 3600) // 60):02d}:{int(duration.total_seconds() % 60):02d}",
            'upload_date': datetime.strptime(snippet['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y %B %d'),
            'timestamp': datetime.strptime(snippet['publishedAt'], '%Y-%m-%dT%H:%M:%SZ').timestamp()
        }
    except Exception as e:
        logging.error(f"Error fetching video details for {video_id}: {e}")
        return None

def process_timestamp(timestamp_str: str) -> Optional[str]:
    """Convert any timestamp format to HH:MM:SS"""
    if not timestamp_str:
        return None
        
    timestamp_str = timestamp_str.strip('[]')
    
    try:
        if ':' in timestamp_str:
            parts = timestamp_str.split(':')
            if len(parts) == 3:
                return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
            elif len(parts) == 2:
                return f"00:{int(parts[0]):02d}:{int(parts[1]):02d}"
        
        total_seconds = float(timestamp_str)
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError) as e:
        logging.error(f"Error processing timestamp {timestamp_str}: {e}")
        return None

def create_timestamp_map(transcript: List[Dict]) -> Dict[str, str]:
    """Create accurate timestamp mapping from transcript"""
    timestamp_map = {}
    for entry in transcript:
        if entry.get('true_video_timestamp'):
            clean_timestamp = process_timestamp(entry['true_video_timestamp'])
            if clean_timestamp:
                text = entry.get('text', '').strip().lower()
                if text:
                    timestamp_map[text] = clean_timestamp
    return timestamp_map

def clean_text_content(text: str) -> str:
    """Clean text content while preserving important information"""
    # Remove markdown
    text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
    
    # Remove duplicate timestamps
    text = re.sub(r'\[\d{2}:\d{2}:\d{2}\](.*?)\[\d{2}:\d{2}:\d{2}\]', r'\1', text)
    
    # Remove explicit timestamp mentions
    text = re.sub(r'at \d{2}:\d{2}:\d{2}', '', text)
    text = re.sub(r'timestamp \d{2}:\d{2}:\d{2}', '', text)
    
    # Clean up numeric timestamps
    text = re.sub(r'\[(\d+\.?\d*)\]', lambda m: f'[{process_timestamp(m.group(1))}]', text)
    
    # Remove redundant markers
    text = re.sub(r'\[ALL-IN\]\s*\[ALL-IN\]', '[ALL-IN]', text)
    text = re.sub(r'\[ELIMINATION\]\s*\[ELIMINATION\]', '[ELIMINATION]', text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove common redundant phrases
    text = re.sub(r'Key Moments?:?\s*', '', text)
    text = re.sub(r'Summary:?\s*', '', text)
    text = re.sub(r'^\d+\.\s*', '', text)  # Remove leading numbers
    
    return text.strip()

def validate_timestamp(timestamp: str, video_duration: str) -> bool:
    """Validate timestamp against video duration"""
    try:
        ts_parts = timestamp.split(':')
        dur_parts = video_duration.split(':')
        
        ts_seconds = sum(int(x) * 60 ** i for i, x in enumerate(reversed(ts_parts)))
        dur_seconds = sum(int(x) * 60 ** i for i, x in enumerate(reversed(dur_parts)))
        
        return 0 <= ts_seconds <= dur_seconds
    except Exception as e:
        logging.error(f"Error validating timestamp {timestamp}: {e}")
        return False

def format_entry(text: str, timestamp: str, video_id: str) -> str:
    """Format a summary entry with proper timestamp link"""
    cleaned_text = clean_text_content(text)
    if not timestamp:
        return cleaned_text
        
    seconds = sum(int(x) * 60 ** i for i, x in enumerate(reversed(timestamp.split(':'))))
    return (
        f'<a href="https://www.youtube.com/watch?v={video_id}&t={seconds}" '
        f'target="_blank" class="highlighted-timestamp">[{timestamp}]</a> {cleaned_text}'
    )

def process_section_lines(section_lines: List[str], timestamp_map: Dict[str, str], 
                         video_id: str, video_duration: str) -> List[str]:
    """Process a section of lines and format them with timestamps"""
    processed_entries = []
    for entry in section_lines:
        timestamp = None
        ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', entry)
        if ts_match:
            timestamp = ts_match.group(1)
        text = re.sub(r'\[[\d:\.]+\]\s*-?\s*', '', entry).strip()
        
        if not timestamp or not validate_timestamp(timestamp, video_duration):
            timestamp = timestamp_map.get(text.lower())
        
        formatted = format_entry(text, timestamp, video_id)
        if formatted and formatted not in processed_entries:
            processed_entries.append(formatted)
    
    return processed_entries

def merge_and_format_summaries(summaries: List[Dict]) -> Dict:
    """Merge and format summaries with accurate timestamps"""
    merged = {}
    
    for summary in summaries:
        video_id = summary.get("video_id")
        if not video_id:
            continue
            
        video_details = get_video_details(video_id)
        if not video_details:
            continue
            
        timestamp_map = create_timestamp_map(summary.get("transcript", []))
        
        if video_id not in merged:
            merged[video_id] = {
                "key_moments": [],
                "standout_players": [],
                "strategic_insights": [],
                "video_details": video_details
            }
        
        for chunk in summary.get("summaries", []):
            current_section = "key_moments"
            section_lines = []
            
            for line in chunk.get("summary", "").split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                if "standout players:" in line.lower():
                    if section_lines:
                        processed = process_section_lines(
                            section_lines, timestamp_map, 
                            video_id, video_details['duration']
                        )
                        merged[video_id][current_section].extend(processed)
                    current_section = "standout_players"
                    section_lines = []
                elif "strategic insights:" in line.lower():
                    if section_lines:
                        processed = process_section_lines(
                            section_lines, timestamp_map, 
                            video_id, video_details['duration']
                        )
                        merged[video_id][current_section].extend(processed)
                    current_section = "strategic_insights"
                    section_lines = []
                else:
                    section_lines.append(line)
            
            # Process remaining lines
            if section_lines:
                processed = process_section_lines(
                    section_lines, timestamp_map, 
                    video_id, video_details['duration']
                )
                merged[video_id][current_section].extend(processed)
    
    return merged

def generate_html_report(summaries: List[Dict]) -> str:
    """Generate HTML report"""
    merged_data = merge_and_format_summaries(summaries)
    videos = []
    
    for video_id, data in merged_data.items():
        try:
            video_data = {
                'id': video_id,
                'title': data['video_details']['title'],
                'duration': data['video_details']['duration'],
                'upload_date': data['video_details']['upload_date'],
                'key_moments': data['key_moments'],
                'standout_players': data['standout_players'],
                'strategic_insights': data['strategic_insights']
            }
            videos.append(video_data)
        except Exception as e:
            logging.error(f"Error processing video {video_id}: {e}")
            continue

    videos.sort(key=lambda x: merged_data[x['id']]['video_details']['timestamp'], reverse=True)

    template = env.get_template(TEMPLATE_FILE)
    rendered_html = template.render(
        videos=videos,
        last_updated=CURRENT_TIME,
        current_user=CURRENT_USER
    )

    report_path = os.path.join(REPORTS_PATH, "latest_report.html")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(rendered_html)

    return report_path

def update_github_html(html_content: str) -> None:
    """Update GitHub repository with generated HTML"""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        contents = repo.get_contents(HTML_FILE_PATH)
        commit_message = f"Update report {CURRENT_TIME}"
        repo.update_file(contents.path, commit_message, html_content, contents.sha)
        logging.info("HTML file updated successfully in GitHub")
    except Exception as e:
        logging.error(f"Failed to update GitHub repository: {e}")


# Main function adjusted for clarity and security
def main():
    logging.info("Starting Report Generator...")
    try:
        summaries = []
        for filename in os.listdir(SUMMARY_PATH):
            if filename.endswith(".json"):
                path = os.path.join(SUMMARY_PATH, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        summaries.append(json.load(f))
                except json.JSONDecodeError as e:
                    logging.error(f"JSON decoding error in {filename}: {e}")
                    continue

        if not summaries:
            logging.warning("No summaries found")
            return

        report_path = generate_html_report(summaries)
        logging.info(f"Report generated at {report_path}")

        with open(report_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        update_github_html(html_content)

        logging.info("Report successfully updated on GitHub")

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        raise

if __name__ == "__main__":
    main()