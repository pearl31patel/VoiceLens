import asyncio
import json

import websockets


class DeepgramStream:
    def __init__(self, api_key, on_utterance):
        self.api_key = api_key
        self.on_utterance = on_utterance

        self.audio_queue = asyncio.Queue()
        self.final_transcript_parts = []
        self.closed = asyncio.Event()

    async def send_audio(self, audio):
        if not self.closed.is_set():
            await self.audio_queue.put(audio)

    async def close(self):
        self.closed.set()
        await self.audio_queue.put(None)

    async def run(self):
        url = (
            "wss://api.deepgram.com/v1/listen"
            "?encoding=mulaw"
            "&sample_rate=8000"
            "&channels=1"
            "&model=nova-2-phonecall"
            "&smart_format=true"
            "&interim_results=true"
            "&endpointing=900"
            "&utterance_end_ms=1000"
        )

        headers = {
            "Authorization": f"Token {self.api_key}",
        }

        async with websockets.connect(url, additional_headers=headers) as websocket:
            audio_sender = asyncio.create_task(
                self.send_audio_to_deepgram(websocket)
            )

            transcript_receiver = asyncio.create_task(
                self.receive_transcripts_from_deepgram(websocket)
            )

            done_tasks, pending_tasks = await asyncio.wait(
                {audio_sender, transcript_receiver},
                return_when=asyncio.FIRST_EXCEPTION,
            )

            for task in pending_tasks:
                task.cancel()

    async def send_audio_to_deepgram(self, websocket):
        while True:
            audio_chunk = await self.audio_queue.get()

            if audio_chunk is None:
                await websocket.send(json.dumps({"type": "CloseStream"}))
                return

            await websocket.send(audio_chunk)

    async def receive_transcripts_from_deepgram(self, websocket):
        async for message in websocket:
            data = json.loads(message)

            if data.get("type") == "Results":
                await self.handle_transcript_result(data)

            elif data.get("type") == "UtteranceEnd":
                await self.send_complete_utterance()

    async def handle_transcript_result(self, data):
        transcript = (
            data.get("channel", {})
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )

        if not transcript:
            return

        if data.get("is_final"):
            self.final_transcript_parts.append(transcript)

        if data.get("speech_final"):
            await self.send_complete_utterance()

    async def send_complete_utterance(self):
        full_text = " ".join(self.final_transcript_parts).strip()
        self.final_transcript_parts.clear()

        if full_text:
            await self.on_utterance(full_text)
