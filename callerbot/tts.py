import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests


class SpeechMaker:
    def __init__(self, settings):
        self.settings = settings
        self.tts_provider = os.getenv("TTS_PROVIDER", "macos").lower().strip()

    async def make_mulaw(self, text):
        return await asyncio.to_thread(self.make_mulaw_audio, text)

    def make_mulaw_audio(self, text):
        speakable_text = self.make_text_speakable(text)

        if self.tts_provider == "elevenlabs":
            return self.make_elevenlabs_audio(speakable_text)

        return self.make_macos_audio(speakable_text)

    def make_elevenlabs_audio(self, text):
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()

        if not api_key:
            raise RuntimeError("Missing ELEVENLABS_API_KEY in .env")

        if not voice_id:
            raise RuntimeError("Missing ELEVENLABS_VOICE_ID in .env")

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Install it with: brew install ffmpeg")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.42,
                "similarity_boost": 0.82,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"ElevenLabs TTS failed: {response.status_code} {response.text}"
            )

        with tempfile.TemporaryDirectory() as temp_folder:
            temp_path = Path(temp_folder)
            mp3_path = temp_path / "speech.mp3"

            mp3_path.write_bytes(response.content)

            ffmpeg_result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(mp3_path),
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-f",
                    "mulaw",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            return ffmpeg_result.stdout

    def make_macos_audio(self, text):
        if not shutil.which("say"):
            raise RuntimeError("macOS 'say' command not found.")

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Install it with: brew install ffmpeg")

        voice = getattr(self.settings, "macos_tts_voice", "Ava")
        rate = str(getattr(self.settings, "macos_tts_rate", 135))

        with tempfile.TemporaryDirectory() as temp_folder:
            temp_path = Path(temp_folder)
            aiff_path = temp_path / "speech.aiff"

            say_command = [
                "say",
                "-v",
                voice,
                "-r",
                rate,
                "-o",
                str(aiff_path),
                text,
            ]

            subprocess.run(
                say_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            ffmpeg_result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(aiff_path),
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-f",
                    "mulaw",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            return ffmpeg_result.stdout

    def make_text_speakable(self, text):
        text = " ".join(text.strip().split())

        replacements = {
            "04/18/1991": "April eighteenth, nineteen ninety one",
            "805-555-0142": "eight zero five, five five five, zero one four two",
            "10 AM": "ten A M",
            "9AM": "nine A M",
            "9 AM": "nine A M",
            "8AM": "eight A M",
            "8 AM": "eight A M",
            "DOB": "date of birth",
            "Dr.": "Doctor",
        }

        for old_text, new_text in replacements.items():
            text = text.replace(old_text, new_text)

        if text and text[-1] not in ".!?":
            text += "."

        return text