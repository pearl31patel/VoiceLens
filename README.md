# AI Voice Patient Caller Simulator

AI voice automation project simulates realistic patient phone calls for testing healthcare voice agents.

This project places outbound calls, behaves like a patient, listens to the agent response, records the conversation, transcribes both sides, and generates a QA-style bug report from the call evidence.

---

## Project Overview

This project was built to test how well a healthcare voice agent handles real patient conversations. This implemented bot acts like a realistic patient and follows different call scenarios such as appointment booking, rescheduling, cancellation, and general patient requests.

After each call, the system saves the transcript, metadata, call events, and recording. These files can then be used to generate a structured bug report.

---

## What It Does

* Starts outbound calls using Twilio Programmable Voice
* Connects the phone call to a Python WebSocket using Twilio Media Streams
* Streams live call audio to Deepgram for transcription
* Uses a scenario-aware patient brain to decide what the patient should say next
* Uses OpenAI Text-to-Speech to generate patient voice responses
* Streams generated audio back into the live phone call
* Saves transcripts, metadata, event logs, and call recordings
* Generates a QA-style bug report from the collected call evidence
* Restricts outbound calls to one approved assessment number only

---

## Tech Stack

* Python
* FastAPI
* WebSockets
* Twilio Programmable Voice
* Twilio Media Streams
* Deepgram Speech-to-Text
* OpenAI Text-to-Speech
* FFmpeg
* ngrok
* dotenv

---

## Project Structure

```text
.
├── callerbot/
│   ├── analyzer.py
│   ├── brain.py
│   ├── config.py
│   ├── server.py
│   ├── twilio_client.py
│   └── utils.py
│
├── data/
│   └── calls/
│       └── 20260619-143012_appt_simple/
│           ├── metadata.json
│           ├── transcript.txt
│           ├── events.jsonl
│           └── recording.mp3
│
├── run_calls.py
├── README.md
├── ARCHITECTURE.md
├── BUG_REPORT.md
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Setup Instructions

### 1. Create Required Accounts

You need the following accounts and API keys:

* Twilio account with a voice-capable phone number
* Deepgram API key
* OpenAI API key
* ngrok account or another HTTPS tunnel provider

---

### 2. Clone the Repository

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

---

### 3. Create a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate
```

For Windows:

```bash
.venv\Scripts\activate
```

---

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 5. Install FFmpeg

For Mac:

```bash
brew install ffmpeg
```

For Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

---

### 6. Configure Environment Variables

Create a `.env` file from the example file:

```bash
cp .env.example .env
```

Then fill in the required values:

```env
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=your_twilio_phone_number

DEEPGRAM_API_KEY=your_deepgram_api_key
OPENAI_API_KEY=your_openai_api_key

PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app
```

Do not commit your `.env` file.

---

## Running the Project

### 1. Start a Public Tunnel

In one terminal, run:

```bash
ngrok http 8000
```

Copy the HTTPS forwarding URL and add it to your `.env` file as:

```env
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app
```

---

### 2. Start the Webhook Server

In another terminal, run:

```bash
uvicorn callerbot.server:app --host 0.0.0.0 --port 8000
```

The FastAPI server will listen for Twilio webhook requests and WebSocket audio streams.

---

### 3. Run Test Calls

Open a second terminal with the same virtual environment active:

```bash
python run_calls.py --count 10
```

This command runs the first 10 patient scenarios and saves the output under:

```text
data/calls/
```

---

## Output Format

Each call creates a separate folder inside `data/calls/`.

Example:

```text
data/calls/20260619-143012_appt_simple/
  metadata.json
  transcript.txt
  events.jsonl
  recording.mp3
```

### transcript.txt

Contains both sides of the conversation:

```text
AGENT: Hello, how can I help you today?
PATIENT: Hi, I want to book an appointment.
AGENT: Sure, what type of appointment do you need?
PATIENT: I need a regular checkup.
```

### metadata.json

Stores call details such as:

* Scenario name
* Twilio call SID
* Call start time
* Call end time
* Call status

### events.jsonl

Stores structured call events such as:

* Agent speech detected
* Patient response generated
* Audio streamed
* Transcription received
* Call completed

### recording.mp3

Stores the recorded call audio for review and evidence.

---

## Generate Bug Report

After running the calls, generate a bug report using:

```bash
python -m callerbot.analyzer --calls data/calls --out BUG_REPORT.md
```

This creates a QA-style report based on the call transcripts and evidence.

The report may include:

* Failed appointment scheduling flows
* Incorrect agent responses
* Long pauses
* Confusing conversation behavior
* Missed patient intent
* Handoff issues
* Transcript-based evidence

---

## Safety Control

This project is locked to one approved phone number:

```text
+1-805-439-8008
```

The app will refuse to call any other number.

This was added to make sure the system is used only for the approved assessment line and not for random outbound calling.

---

## Example Use Case

A healthcare company can use this type of voice AI testing system to evaluate how well its appointment scheduling agent handles real patient calls.

For example, the AI patient may call and say:

```text
Hi, I need to reschedule my appointment from Monday to Wednesday.
```

The system then checks if the agent understands the request, asks the right follow-up questions, confirms the new time, and completes the call correctly.

If the agent fails, the transcript and recording can be used as evidence in the bug report.

---

## Key Features

* Real-time AI voice conversation
* Live transcription
* Scenario-based patient behavior
* Automated call execution
* Audio recording
* Transcript generation
* QA bug report generation
* Safe outbound call restriction
* Evidence-based testing workflow

---



## Skills Demonstrated

This project demonstrates experience with:

* Voice AI systems
* Real-time audio streaming
* WebSocket communication
* Twilio Programmable Voice
* Speech-to-text integration
* Text-to-speech integration
* FastAPI backend development
* AI agent behavior design
* Healthcare workflow testing
* QA automation
* Evidence-based bug reporting

---

## Author

Pearl Patel
