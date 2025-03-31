import os
import json
import requests
import logging
import time
import tempfile
import shutil
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Load environment variables
load_dotenv()

# --- Configuration ---
TRANSCRIPT_DIR = os.getenv("JSON_FILE_PATH")
OUTPUT_JSON_PATH = os.getenv("OUTPUT_JSON_PATH")
PROCESSED_VIDEOS_PATH = os.getenv("PROCESSED_VIDEOS_PATH")
API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
MAX_INPUT_TOKENS = 55000
TIMEOUT = 60
RETRIES = 5

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler("deepseek_analysis.log", encoding='utf-8'),
        logging.StreamHandler()
    ],
    encoding='utf-8'
)

# --- Helper Functions ---

def load_or_create_json(file_path, default_data):
    """Loads JSON data from a file or creates it with default data."""
    if not os.path.exists(file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=4)
            return default_data
        except OSError as e:
            logging.error(f"Error creating file {file_path}: {e}")
            return None
    else:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logging.error(f"Error loading JSON from {file_path}: {e}")
            return None

def atomic_write_json(data, file_path, indent=4):
    """Atomically writes JSON data to a file, handling potential errors."""
    try:
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as temp_file:
            json.dump(data, temp_file, indent=indent)
            temp_file.flush()
            os.fsync(temp_fd)
        shutil.move(temp_path, file_path)
    except (OSError, ValueError) as e:
        logging.error(f"Error during atomic write to {file_path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

def trim_transcript_for_tokens(transcript_text, max_input_tokens=MAX_INPUT_TOKENS):
    """Trims the transcript text to fit within the maximum token limit."""
    tokens = transcript_text.split()
    if len(tokens) > max_input_tokens:
        logging.warning(f"Transcript exceeds token limit. Trimming to {max_input_tokens} tokens.")
        return ' '.join(tokens[:max_input_tokens])
    return transcript_text

def make_deepseek_request(url, data, api_key, timeout=TIMEOUT, retries=RETRIES):
    """Makes a request to the DeepSeek API with retries and timeout."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    try:
        response = session.post(url, headers=headers, data=json.dumps(data), timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Request to DeepSeek API failed: {e}")
        return None

def convert_to_seconds(timestamp):
    """Converts a colon-separated timestamp string (HH:MM:SS) into total seconds."""
    parts = list(map(int, timestamp.strip('[]').split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0

def generate_summary(chunk, video_id, chunk_number, previous_summary=None):
    """Generates a summary for a given chunk of transcript."""
    transcript_text = "\n".join(
        f"[{entry.get('true_video_timestamp', '00:00:00')}] {entry.get('text', '')}"
        for entry in chunk.get("transcript", [])
    )

    if not transcript_text.strip():
        logging.warning(f"Chunk {chunk_number} is empty. Skipping.")
        return None

    transcript_text = trim_transcript_for_tokens(transcript_text)
    context_info = (
        f"Previous summary context:\n{previous_summary}"
        if previous_summary
        else "No previous context available."
    )
    chunk_start_time = chunk.get("start_time", "00:00:00")

    prompt = f"""
You are a specialized analyst for high-stakes poker tournament videos with professional commentary.

Your goal is to create an insightful yet concise summary of key poker moments. Prioritize key strategic decisions, player moves, and game-changing hands. Ignore casual talk, promotions, or off-topic banter.

Important instructions:
- Use the timestamps from the transcript text directly in your summary for precise event tracking.
- Assume the chunk starts at **[{chunk_start_time}]** and adjust referenced timestamps accordingly.
- Highlight key moments such as:
    - **[ALL-IN]**, **[RAISE]**, **[FOLD]**
    - **[CHECK]**, **[BET]**, **[CALL]**, **[3-BET]**, **[4-BET]**, **[5-BET]**, **[C-BET]**
    - **[BLUFF]**, **[TRAP]**, **[SLOWPLAY]**, **[ISOLATION PLAY]**, **[FLOAT]**
    - **[BUBBLE]**, **[FINAL TABLE]**, **[CHIP LEAD]**, **[ELIMINATION]**
    - **[TILT]**, **[LEVELING]**, **[ICM PRESSURE]**
- Emphasize strategic decisions, table dynamics, and momentum shifts — even if no major action occurs.
- Identify standout players, their playing style, and pivotal moments.
- **If no strategic poker insights are found, respond with: "NO INSIGHTFUL POKER CONTENT."**

{context_info}

Transcript Chunk:
{transcript_text}

Output:
"""
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192
    }

    response_data = make_deepseek_request(DEEPSEEK_ENDPOINT, data, API_KEY)

    if response_data:
        try:
            summary = response_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if "NO INSIGHTFUL POKER CONTENT" in summary:
                logging.info(f"Chunk {chunk_number} has no key poker content. Skipping.")
                return None
            logging.info(f"Chunk {chunk_number} summarized successfully.")
            return summary
        except (AttributeError, IndexError, KeyError) as e:
            logging.error(f"Error parsing DeepSeek response for chunk {chunk_number}: {e}")
            logging.error(f"Response data: {response_data}")
            return None
    else:
        return None

def main():
    """Main function to process transcripts and generate summaries."""
    processed_videos = load_or_create_json(PROCESSED_VIDEOS_PATH, [])

    if processed_videos is None:
        logging.error(f"Could not load or create {PROCESSED_VIDEOS_PATH}. Exiting.")
        return

    if isinstance(processed_videos, list):
        processed_set = {
            entry.get('video_id')
            for entry in processed_videos
            if isinstance(entry, dict) and entry.get('summary_completed')
        }
    else:
        logging.error(f"{PROCESSED_VIDEOS_PATH} is not a list. Resetting.")
        processed_videos = []
        processed_set = set()

    for filename in os.listdir(TRANSCRIPT_DIR):
        if not filename.endswith(".json"):
            continue

        file_path = os.path.join(TRANSCRIPT_DIR, filename)
        data = load_or_create_json(file_path, None)
        if data is None:
            logging.error(f"Skipping {filename} due to load error.")
            continue

        video_id = data.get("video_id")
        if not video_id:
            logging.warning(f"Skipping {filename} (Missing video_id)")
            continue

        if video_id in processed_set:
            logging.info(f"⏩ Skipping {video_id} (Already Processed)")
            continue

        chunks = data.get("chunks", [])
        logging.info(f"Loaded {len(chunks)} chunks from {filename}.")

        summaries = []
        previous_summary = None
        start_time = time.time()
        last_log_time = start_time

        for idx, chunk in enumerate(tqdm(chunks, desc="Summarizing", unit="chunk", dynamic_ncols=True), start=1):
            retry_attempts = 0
            while retry_attempts < RETRIES:
                summary = generate_summary(chunk, video_id, idx, previous_summary)
                if summary:
                    summaries.append({"chunk_id": idx, "summary": summary})
                    previous_summary = summary
                    break
                else:
                    retry_attempts += 1
                    logging.warning(f"Retrying chunk {idx} (attempt {retry_attempts}/{RETRIES})")
                    time.sleep(2 ** retry_attempts)

            current_time = time.time()
            if current_time - last_log_time > 10 or idx == len(chunks):
                elapsed_time = current_time - start_time
                if idx > 0:
                    avg_time_per_chunk = elapsed_time / idx
                    remaining_chunks = len(chunks) - idx
                    remaining_time = avg_time_per_chunk * remaining_chunks
                    logging.info(f"ETA: {remaining_time//60}m {round(remaining_time % 60)}s remaining.")
                last_log_time = current_time

        try:
            atomic_write_json({"video_id": video_id, "summaries": summaries}, os.path.join(OUTPUT_JSON_PATH, f"{video_id}.json"))
        except Exception:
            logging.error("Failed to save summary. Continuing to next video.")
            continue

        processed_videos.append({
            "video_id": video_id,
            "summary_completed": True,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        })
        try:
            atomic_write_json(processed_videos, PROCESSED_VIDEOS_PATH)
        except Exception:
            logging.critical("Failed to write list of processed files. Data may be lost!")
            continue

if __name__ == "__main__":
    main()