import os
import json
import requests
import logging
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv
import isodate  # Added for parsing video duration

# Load environment variables
load_dotenv()

# Base Path — Ensures everything is relative to the script's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure necessary directories exist
LOGS_PATH = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_PATH, exist_ok=True)

DATA_PATH = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_PATH, exist_ok=True)

# Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")
VIDEO_QUEUE_PATH = os.path.join(DATA_PATH, "video_queue.json")
PROCESSED_VIDEOS_PATH = os.path.join(DATA_PATH, "processed_videos.json")
LAST_PROCESSED_PATH = os.path.join(DATA_PATH, "last_processed.json")

# YouTube API URL Definition
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_PATH, "video_collector.log"), mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Default Starting Date for First Run (Fixed to February 1, 2025, 12:00 AM)
DEFAULT_START_DATE = "2025-02-01T00:00:00Z"
logging.info(f"✅ Default Start Date Set to: {DEFAULT_START_DATE}")

# === Initial Startup Log ===
logging.info("🚀 Starting Video Collector Script...")

def load_json(file_path, default_value=[]):
    """Loads JSON file or returns default value if missing or invalid."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        save_json(default_value, file_path)
        return default_value

    with open(file_path, 'r', encoding='utf-8') as file:
        try:
            data = json.load(file)
            if isinstance(data, list):
                return data
            return default_value
        except json.JSONDecodeError:
            save_json(default_value, file_path)
            return default_value

def save_json(data, file_path):
    """Saves JSON data to file."""
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4)
    logging.info(f"Data saved to {file_path}")

def get_video_details(video_id):
    """Fetches video details like duration."""
    url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        if "items" in data and len(data["items"]) > 0:
            duration = data["items"][0]["contentDetails"]["duration"]
            return parse_duration(duration)
    except Exception as e:
        logging.warning(f"Failed to fetch video details for {video_id}: {e}")
    return 0

def parse_duration(duration_str):
    """Parses ISO 8601 duration format to seconds."""
    try:
        duration = isodate.parse_duration(duration_str)
        return int(duration.total_seconds())
    except Exception:
        return 0

def fetch_videos_from_channel():
    """Fetches video IDs from the channel and filters by duration & date."""
    processed_videos = load_json(PROCESSED_VIDEOS_PATH, default_value=[])
    qualifying_videos = []

    last_processed_date = load_json(LAST_PROCESSED_PATH, default_value={"last_processed_date": DEFAULT_START_DATE})
    published_after = last_processed_date.get("last_processed_date", DEFAULT_START_DATE)

    params = {
        'part': 'id',
        'channelId': CHANNEL_ID,
        'maxResults': 50,
        'order': 'date',
        'type': 'video',
        'publishedAfter': published_after,
        'key': YOUTUBE_API_KEY
    }

    logging.info(f"🔍 Checking videos published after: {published_after}")

    total_videos = 0

    with tqdm(desc="Fetching Videos", dynamic_ncols=True) as pbar:
        while True:
            try:
                response = requests.get(YOUTUBE_API_URL, params=params)
                data = response.json()

                if not data.get('items'):
                    logging.info("⚠️ No videos found — check your filters or API settings.")
                    break

                new_videos = 0
                for idx, item in enumerate(data.get('items', []), start=1):
                    video_id = item['id']['videoId']

                    if video_id in processed_videos:
                        continue

                    video_duration = get_video_details(video_id)
                    if video_duration < 600:
                        logging.info(f"⏩ Skipping {video_id} (Duration: {video_duration // 60} mins)")
                        continue

                    logging.info(f"✅ Qualifying Video: {video_id} (Duration: {video_duration // 60} mins)")
                    qualifying_videos.append({"video_id": video_id, "video_index": total_videos + 1})
                    processed_videos.append(video_id)
                    new_videos += 1
                    total_videos += 1

                pbar.update(1)
                pbar.set_postfix({"New Videos": total_videos})

                if 'nextPageToken' in data:
                    params['pageToken'] = data['nextPageToken']
                else:
                    logging.info("✅ No more pages to fetch. Finishing up.")
                    break
            except Exception as e:
                logging.error(f"API Error: {e}")
                break

    qualifying_videos = sorted(qualifying_videos, key=lambda x: x['video_index'])

    save_json(qualifying_videos, VIDEO_QUEUE_PATH)
    save_json(processed_videos, PROCESSED_VIDEOS_PATH)
    save_json({"last_processed_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")}, LAST_PROCESSED_PATH)

    logging.info(f"✅ Found {total_videos} new qualifying videos published after {published_after}.")

if __name__ == "__main__":
    fetch_videos_from_channel()
