# Pretty Good AI Voice Bot Challenge

This is my Python voice-caller simulator for the Pretty Good AI challenge. The bot calls the assessment line, behaves like a realistic patient, records/transcribes the conversation, and creates a QA-style bug report from the call evidence.

The app is intentionally locked to the assessment number: `+1-805-439-8008`. It will refuse to call any other number.

## What it does

- Starts outbound calls using Twilio Programmable Voice.
- Connects the phone call to a Python WebSocket using Twilio bidirectional Media Streams.
- Streams the AI agent audio to Deepgram for live transcription.
- Uses a scenario-aware patient brain to decide what to say next.
- Uses OpenAI TTS to generate patient speech and streams it back into the call.
- Saves transcripts, metadata, and Twilio call recordings.
- Generates a bug report from the transcripts.

## Setup

### 1. Create accounts / keys

You need:

- Twilio account with a voice-capable phone number
- Deepgram API key
- OpenAI API key
- ngrok or another HTTPS tunnel

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Install ffmpeg too. On Mac:

```bash
brew install ffmpeg
```

On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in your Twilio, Deepgram, OpenAI, and public URL values.

### 4. Start a public tunnel

```bash
ngrok http 8000
```

Copy the HTTPS forwarding URL into `.env` as `PUBLIC_BASE_URL`.

### 5. Start the webhook server

```bash
uvicorn callerbot.server:app --host 0.0.0.0 --port 8000
```

### 6. Run 10 calls

Open a second terminal with the same virtual environment active:

```bash
python run_calls.py --count 10
```

The app will run the first 10 scenarios and save outputs under:

```text
data/calls/
```

### 7. Generate the bug report

```bash
python -m callerbot.analyzer --calls data/calls --out BUG_REPORT.md
```

## Expected output structure

Each call gets a folder like:

```text
data/calls/20260619-143012_appt_simple/
  metadata.json
  transcript.txt
  events.jsonl
  recording.mp3
```

`transcript.txt` contains both sides:

```text
AGENT: ...
PATIENT: ...
AGENT: ...
PATIENT: ...
```

## Submission checklist

Commit these to GitHub:

- `callerbot/`
- `run_calls.py`
- `README.md`
- `ARCHITECTURE.md`
- `.env.example`
- `BUG_REPORT.md`
- `data/calls/*/transcript.txt`
- `data/calls/*/recording.mp3`

Do not commit `.env`.

## Notes

The first run may need tuning because every voice agent behaves differently. I usually run 1–2 calls first, listen to the audio, then adjust pacing, scenario prompts, and max turns before running the final 10 calls.
