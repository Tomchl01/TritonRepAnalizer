import os
import json
import re
import logging
from tqdm import tqdm
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data")
TRANSCRIPTS_PATH = os.path.join(DATA_PATH, "cleaned_transcripts")
VIDEO_QUEUE_PATH = os.path.join(DATA_PATH, "video_queue.json")

os.makedirs(TRANSCRIPTS_PATH, exist_ok=True)

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

# Patterns for content cleaning
IRRELEVANT_PATTERNS = [
    r"\[.*\]",
    r"http[s]?://",
    r"\[.*noise.*\]",
    r"\[.*sound.*\]",
    r"\[.*laughter.*\]"
]

def load_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def get_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        formatter = JSONFormatter()
        return json.loads(formatter.format_transcript(transcript))
    except Exception as e:
        logging.warning(f"Transcript not available for video {video_id}: {e}")
        return []

def filter_transcript(transcript):
    filtered_transcript = []
    for entry in transcript:
        text = entry['text']
        for pattern in IRRELEVANT_PATTERNS:
            text = re.sub(pattern, "", text)
        if text.strip() and entry['duration'] >= 3.0:
            filtered_transcript.append({
                'text': text.strip(),
                'start': entry['start'],
                'duration': entry['duration']
            })
    return filtered_transcript

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"[{hours:02}:{minutes:02}:{seconds:02}]"

def chunk_transcript(transcript, max_tokens=20000):
    transcript = filter_transcript(transcript)
    chunks = []
    current_chunk = []
    total_tokens = 0
    chunk_id = 1

    for entry in transcript:
        num_tokens = len(entry['text'].split())
        true_video_timestamp = format_timestamp(entry['start'])

        if total_tokens + num_tokens > max_tokens:
            chunks.append({
                "chunk_id": chunk_id,
                "start_time": current_chunk[0]['start'],
                "end_time": current_chunk[-1]['start'] + current_chunk[-1]['duration'],
                "transcript": current_chunk
            })
            current_chunk = []
            total_tokens = 0
            chunk_id += 1

        entry['true_video_timestamp'] = true_video_timestamp
        current_chunk.append(entry)
        total_tokens += num_tokens

    if current_chunk:
        chunks.append({
            "chunk_id": chunk_id,
            "start_time": current_chunk[0]['start'],
            "end_time": current_chunk[-1]['start'] + current_chunk[-1]['duration'],
            "transcript": current_chunk
        })

    return chunks

def save_to_json(data, filename):
    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4)
    logging.info(f"✅ Data saved to {filename}")

def main():
    video_queue = load_json(VIDEO_QUEUE_PATH)

    for video in tqdm(video_queue, desc="Fetching Transcripts", unit="video"):
        video_id = video["video_id"]
        save_path = os.path.join(TRANSCRIPTS_PATH, f"{video_id}.json")

        if os.path.exists(save_path):
            logging.info(f"⏩ Transcript already processed: {video_id}")
            continue

        transcript_data = get_transcript(video_id)
        if transcript_data:
            cleaned_data = {
                "video_id": video_id,
                "chunks": chunk_transcript(transcript_data)
            }
            save_to_json(cleaned_data, save_path)

if __name__ == "__main__":
    main()
