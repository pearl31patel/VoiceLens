import asyncio
import audioop
import base64
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from callerbot.config import Settings
from callerbot.deepgram_stt import DeepgramStream
from callerbot.llm_patient import PatientBrain
from callerbot.scenarios import SCENARIOS
from callerbot.storage import CallStore
from callerbot.tts import SpeechMaker


app = FastAPI(title="PG AI Voice Bot")

settings = Settings.from_env()
store = CallStore(settings.call_output_dir)
speech_maker = SpeechMaker(settings)
patient_brain = PatientBrain(settings)
twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

SCENARIO_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


@app.get("/health")
def check_health():
    return {"status": "ok"}


@app.api_route("/twiml", methods=["GET", "POST"])
async def make_twiml(session_id=Query(...), scenario_id=Query(...)):
    if scenario_id not in SCENARIO_BY_ID:
        return PlainTextResponse(f"Unknown scenario: {scenario_id}", status_code=400)

    ws_url = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/media"

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=ws_url)
    stream.parameter(name="session_id", value=session_id)
    stream.parameter(name="scenario_id", value=scenario_id)
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def save_call_status(request: Request):
    form = await request.form()
    call_sid = str(form.get("CallSid", ""))
    status = str(form.get("CallStatus", ""))

    print(f"[call-status] {call_sid}: {status}")
    return {"ok": "true"}


@app.post("/recording-callback")
async def save_recording(request: Request):
    form = await request.form()
    call_sid = str(form.get("CallSid", ""))
    recording_url = str(form.get("RecordingUrl", ""))
    recording_sid = str(form.get("RecordingSid", ""))

    session_id = find_session_from_call_sid(call_sid)

    if not session_id:
        print("[recording-callback] Could not match call SID:", call_sid)
        return {"ok": "false"}

    out_path = store.session_dir(session_id) / "recording.mp3"

    if recording_url:
        try:
            url = f"{recording_url}.mp3"
            response = requests.get(
                url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=60,
            )
            response.raise_for_status()
            out_path.write_bytes(response.content)
        except Exception as exc:
            print("[recording-callback] recording download failed:", repr(exc))
            store.update_metadata(
                session_id,
                {
                    "recording_sid": recording_sid,
                    "recording_url": recording_url,
                    "recording_download_error": repr(exc),
                    "recording_error_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            return {"ok": "false"}

    store.update_metadata(
        session_id,
        {
            "recording_sid": recording_sid,
            "recording_url": recording_url,
            "recording_path": str(out_path),
            "recording_saved_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    print(f"[recording-callback] Saved recording for {session_id}")
    return {"ok": "true"}


@app.websocket("/media")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()
    session = None

    try:
        while True:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            event = message.get("event")

            if event == "start":
                params = message.get("start", {}).get("customParameters", {})
                session_id = params.get("session_id")
                scenario_id = params.get("scenario_id")
                stream_sid = message.get("start", {}).get("streamSid")
                call_sid = message.get("start", {}).get("callSid")

                if not session_id or not scenario_id:
                    await websocket.close()
                    return

                if scenario_id not in SCENARIO_BY_ID:
                    await websocket.close()
                    return

                scenario = SCENARIO_BY_ID[scenario_id]

                session = MediaSession(
                    websocket=websocket,
                    session_id=session_id,
                    stream_sid=stream_sid,
                    call_sid=call_sid,
                    scenario=scenario,
                )

                store.update_metadata(session_id, {"twilio_call_sid": call_sid})
                await session.start_session()

            elif event == "media" and session:
                payload = base64.b64decode(message["media"]["payload"])
                await session.receive_agent_audio(payload)

            elif event == "stop":
                if session:
                    await session.stop_session()
                return

    except WebSocketDisconnect:
        if session:
            await session.stop_session()
    except Exception as exc:
        print("[media] error:", repr(exc))
        if session:
            await session.stop_session()


class MediaSession:
    def __init__(
        self,
        websocket,
        session_id,
        stream_sid,
        call_sid,
        scenario,
    ):
        self.websocket = websocket
        self.session_id = session_id
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.scenario = scenario

        self.transcript = []
        self.turn_count = 0
        self.started_at = datetime.now()
        self.closed = False

        self.bot_speaking = asyncio.Lock()

        self.agent_text_buffer = []
        self.last_agent_text_at = 0.0
        self.last_agent_audio_at = 0.0
        self.last_agent_text = ""
        self.last_agent_text_seen_at = 0.0

        self.last_patient_reply_text = ""
        self.last_patient_reply_at = 0.0

        self.min_text_silence_before_reply = 0.25
        self.min_audio_silence_before_reply = 0.55
        self.first_prompt_wait_seconds = 30.0
        self.pre_speech_pause_seconds = 0.05
        self.agent_rms_threshold = 700

        self.stt = DeepgramStream(
            api_key=settings.deepgram_api_key,
            on_utterance=self.handle_agent_message,
        )

        self.stt_task = None
        self.timeout_task = None
        self.first_prompt_task = None
        self.reply_task = None

    async def start_session(self):
        print(f"[session] started {self.session_id} / {self.scenario.id}")

        store.append_event(
            self.session_id,
            {
                "type": "start",
                "call_sid": self.call_sid,
                "stream_sid": self.stream_sid,
                "scenario_id": self.scenario.id,
            },
        )

        self.stt_task = asyncio.create_task(self.stt.run())
        self.timeout_task = asyncio.create_task(self.stop_after_max_call_time())
        self.first_prompt_task = asyncio.create_task(self.speak_first_if_agent_is_silent())

    async def stop_session(self):
        if self.closed:
            return

        self.closed = True

        try:
            await self.stt.close()
        except Exception as exc:
            print("[session] failed to close STT:", repr(exc))

        for task in [self.stt_task, self.timeout_task, self.first_prompt_task, self.reply_task]:
            if task and not task.done():
                task.cancel()

        store.append_event(self.session_id, {"type": "stop"})
        print(f"[session] stopped {self.session_id}")

    async def receive_agent_audio(self, payload):
        if self.closed:
            return

        await self.stt.send_audio(payload)

        if self.agent_audio_has_voice(payload):
            self.last_agent_audio_at = time.monotonic()

    def should_ignore_short_agent_fragment(self, text):
        cleaned = " ".join(text.strip().lower().split())

        if not cleaned:
            return True

        words = cleaned.replace("?", "").replace(".", "").replace(",", "").split()

        actionable_keywords = [
            "name",
            "birth",
            "dob",
            "phone",
            "number",
            "spell",
            "confirm",
            "correct",
            "yourself",
            "someone else",
            "appointment",
            "schedule",
            "reschedule",
            "cancel",
            "refill",
            "medication",
            "pharmacy",
            "insurance",
            "symptoms",
            "pain",
            "emergency",
            "911",
            "fax",
            "authorized",
            "representative",
            "support",
            "transfer",
            "connect",
            "goodbye",
        ]

        has_actionable_word = any(keyword in cleaned for keyword in actionable_keywords)

        recently_replied = (
            self.last_patient_reply_at > 0
            and time.monotonic() - self.last_patient_reply_at < 4.0
        )

        if recently_replied and len(words) <= 3 and not has_actionable_word:
            print(f"[turn] ignored short trailing fragment: {text!r}")
            return True

        return False

    async def handle_agent_message(self, text):
        if self.closed:
            return

        clean = self.clean_text(text)

        if not clean:
            return

        if self.is_repeated_agent_text(clean):
            print(f"[agent duplicate ignored] {clean}")
            return

        print(f"[agent] {clean}")

        if self.should_ignore_short_agent_fragment(text):
            return

        self.transcript.append(("AGENT", clean))
        store.append_transcript(self.session_id, "AGENT", clean)
        store.append_event(self.session_id, {"type": "agent_utterance", "text": clean})

        if self.is_not_actionable_agent_message(clean):
            print("[agent ignored as non-actionable]")
            return

        self.agent_text_buffer.append(clean)
        self.last_agent_text_at = time.monotonic()

        if self.reply_task and not self.reply_task.done():
            self.reply_task.cancel()

        self.reply_task = asyncio.create_task(self.reply_when_agent_is_done())

    async def reply_when_agent_is_done(self):
        try:
            while not self.closed:
                now = time.monotonic()
                text_silence = now - self.last_agent_text_at
                audio_silence = now - self.last_agent_audio_at

                if (
                    text_silence >= self.min_text_silence_before_reply
                    and audio_silence >= self.min_audio_silence_before_reply
                    and not self.bot_speaking.locked()
                ):
                    break

                await asyncio.sleep(0.1)

            if self.closed:
                return

            latest_agent_text = " ".join(self.agent_text_buffer[-6:]).strip()
            self.agent_text_buffer.clear()

            if not latest_agent_text:
                return

            if self.message_looks_incomplete(latest_agent_text):
                print("[reply] agent text looked incomplete, waiting briefly")
                await asyncio.sleep(0.35)

                if self.closed:
                    return

                if self.agent_text_buffer:
                    return

            reply = patient_brain.next_reply(
                scenario=self.scenario,
                transcript=self.transcript,
                latest_agent_text=latest_agent_text,
                turn_count=self.turn_count,
            )

            patient_text = self.clean_patient_text(reply.say)

            if not patient_text:
                return

            await asyncio.sleep(self.pre_speech_pause_seconds)
            await self.speak_as_patient(patient_text)

            self.turn_count += 1

            if reply.done:
                await asyncio.sleep(1.0)
                await self.finish_call("patient brain marked conversation done")

        except asyncio.CancelledError:
            return
        except Exception as exc:
            print("[reply-after-agent] failed:", repr(exc))
            store.append_event(
                self.session_id,
                {
                    "type": "reply_after_agent_error",
                    "error": repr(exc),
                },
            )

    async def speak_as_patient(self, text):
        if self.closed:
            print("[patient] tried to speak, but session is closed")
            return

        clean = self.clean_patient_text(text)

        if not clean:
            return

        async with self.bot_speaking:
            print(f"[patient] speaking: {clean}")

            self.transcript.append(("PATIENT", clean))
            store.append_transcript(self.session_id, "PATIENT", clean)
            store.append_event(self.session_id, {"type": "patient_utterance", "text": clean})

            try:
                mulaw = await speech_maker.make_mulaw(clean)
                print(f"[patient] generated {len(mulaw)} mulaw bytes")
                await self.send_audio_to_twilio(mulaw)
                print("[patient] finished sending audio to Twilio")

                self.last_patient_reply_text = text
                self.last_patient_reply_at = time.monotonic()
            except Exception as exc:
                print("[patient] TTS/send failed:", repr(exc))
                store.append_event(
                    self.session_id,
                    {
                        "type": "patient_audio_error",
                        "error": repr(exc),
                        "text": clean,
                    },
                )

    async def send_audio_to_twilio(self, mulaw):
        frame_size = 800

        for index in range(0, len(mulaw), frame_size):
            if self.closed:
                return

            chunk = mulaw[index: index + frame_size]

            message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": base64.b64encode(chunk).decode("ascii"),
                },
            }

            await self.websocket.send_text(json.dumps(message))
            await asyncio.sleep(0.001)

        await self.websocket.send_text(
            json.dumps(
                {
                    "event": "mark",
                    "streamSid": self.stream_sid,
                    "mark": {"name": f"patient_turn_{self.turn_count}"},
                }
            )
        )

    async def speak_first_if_agent_is_silent(self):
        await asyncio.sleep(self.first_prompt_wait_seconds)

        if self.transcript or self.closed:
            return

        opening = self.make_opening_line()
        await self.speak_as_patient(opening)

        self.turn_count += 1

    async def stop_after_max_call_time(self):
        await asyncio.sleep(settings.max_call_seconds)

        if self.closed:
            return

        await self.speak_as_patient("Okay, thank you. I have to go now.")
        await asyncio.sleep(1.0)
        await self.finish_call("max call seconds reached")

    async def finish_call(self, reason):
        if self.closed:
            return

        store.append_event(self.session_id, {"type": "ending_call", "reason": reason})
        print(f"[session] ending call: {reason}")

        self.closed = True

        for task in [self.reply_task, self.first_prompt_task, self.timeout_task]:
            if task and not task.done():
                task.cancel()

        try:
            twilio_client.calls(self.call_sid).update(status="completed")
        except Exception as exc:
            print("[end_call] failed to complete call:", repr(exc))

    def make_opening_line(self):
        goal = self.scenario.opening_goal.lower()
        details = self.scenario.details.lower()

        if "sore throat" in goal or "sore throat" in details:
            return (
                f"Hi, this is {self.scenario.patient_name}. "
                "I have had a sore throat for a few days, and I was hoping to schedule a visit."
            )

        if "refill" in goal:
            return f"Hi, this is {self.scenario.patient_name}. I am calling about a medication refill."

        if "cancel" in goal:
            return f"Hi, this is {self.scenario.patient_name}. I need to cancel an appointment."

        if "reschedule" in goal:
            return f"Hi, this is {self.scenario.patient_name}. I need to reschedule an appointment."

        return f"Hi, this is {self.scenario.patient_name}. I was hoping you could help me today."

    def agent_audio_has_voice(self, payload):
        try:
            pcm = audioop.ulaw2lin(payload, 2)
            rms = audioop.rms(pcm, 2)
            return rms > self.agent_rms_threshold
        except Exception:
            return False

    def is_repeated_agent_text(self, text):
        now = time.monotonic()
        current = self.normalize_text(text)
        previous = self.normalize_text(self.last_agent_text)

        if current and current == previous and (now - self.last_agent_text_seen_at) < 4.0:
            return True

        self.last_agent_text = text
        self.last_agent_text_seen_at = now

        return False

    def is_not_actionable_agent_message(self, text):
        lower = text.lower().strip()

        actionable_phrases = [
            "am i speaking",
            "is this",
            "date of birth",
            "birth date",
            "birthday",
            "dob",
            "please tell me",
            "what is your",
            "what's your",
            "phone number",
            "is that correct",
            "how may i help",
            "how can i help",
            "would you like",
            "do you have",
            "preferred",
            "which one",
            "should i book",
            "can i book",
            "confirm",
            "book it",
            "schedule",
            "appointment",
            "pharmacy",
            "insurance",
            "address",
            "email",
            "symptoms",
            "sore throat",
            "acute visit",
            "openings",
            "available",
            "not available",
            "earliest",
            "monday",
            "tomorrow",
            "today",
            "representative",
            "patient support",
            "connect you",
            "transfer",
        ]

        if any(phrase in lower for phrase in actionable_phrases):
            return False

        non_actionable_phrases = [
            "this call may be recorded",
            "recorded for quality",
            "quality and training",
            "thanks for calling",
            "thank you for calling",
            "part of pretty good ai",
        ]

        if any(phrase in lower for phrase in non_actionable_phrases):
            return True

        if lower in {"hello", "hi", "good morning", "good afternoon"}:
            return True

        return False

    def message_looks_incomplete(self, text):
        words = text.lower().strip().split()

        if not words:
            return False

        last = words[-1].strip(".,!?")

        incomplete_endings = {
            "a",
            "an",
            "the",
            "of",
            "to",
            "for",
            "with",
            "because",
            "and",
            "or",
            "but",
            "is",
            "are",
            "am",
            "was",
            "were",
            "there",
            "that",
            "this",
            "at",
            "on",
            "in",
        }

        return last in incomplete_endings

    def clean_text(self, text):
        return " ".join(text.strip().split())

    def clean_patient_text(self, text):
        return self.clean_text(text)

    def normalize_text(self, text):
        return "".join(character.lower() for character in text if character.isalnum())


def find_session_from_call_sid(call_sid):
    for metadata_path in Path(settings.call_output_dir).glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if metadata.get("twilio_call_sid") == call_sid:
            return metadata.get("session_id")

    return None