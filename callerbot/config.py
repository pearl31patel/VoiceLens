import os
from pathlib import Path

from dotenv import load_dotenv


class Settings:
    def __init__(
        self,
        twilio_account_sid,
        twilio_auth_token,
        twilio_from_number,
        public_base_url,
        llm_provider,
        llm_api_key,
        llm_base_url,
        llm_model,
        macos_tts_voice,
        macos_tts_rate,
        deepgram_api_key,
        assessment_number,
        call_output_dir,
        max_call_seconds,
        max_turns,
    ):
        self.twilio_account_sid = twilio_account_sid
        self.twilio_auth_token = twilio_auth_token
        self.twilio_from_number = twilio_from_number
        self.public_base_url = public_base_url

        self.llm_provider = llm_provider
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model

        self.macos_tts_voice = macos_tts_voice
        self.macos_tts_rate = macos_tts_rate

        self.deepgram_api_key = deepgram_api_key

        self.assessment_number = assessment_number
        self.call_output_dir = call_output_dir
        self.max_call_seconds = max_call_seconds
        self.max_turns = max_turns

    @classmethod
    def from_env(cls):
        load_dotenv()

        public_base_url = get_required_env_value("PUBLIC_BASE_URL").rstrip("/")

        assessment_number = (
            os.getenv("ASSESSMENT_NUMBER", "+18054398008")
            .replace("-", "")
            .replace(" ", "")
        )

        return cls(
            twilio_account_sid=get_required_env_value("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=get_required_env_value("TWILIO_AUTH_TOKEN"),
            twilio_from_number=get_required_env_value("TWILIO_FROM_NUMBER"),
            public_base_url=public_base_url,

            llm_provider=os.getenv("LLM_PROVIDER", "groq"),
            llm_api_key=get_required_env_value("LLM_API_KEY"),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            llm_model=os.getenv("LLM_MODEL", "llama-3.1-8b-instant"),

            macos_tts_voice=os.getenv("MACOS_TTS_VOICE", "Ava"),
            macos_tts_rate=int(os.getenv("MACOS_TTS_RATE", "135")),

            deepgram_api_key=get_required_env_value("DEEPGRAM_API_KEY"),

            assessment_number=assessment_number,
            call_output_dir=Path(os.getenv("CALL_OUTPUT_DIR", "data/calls")),
            max_call_seconds=int(os.getenv("MAX_CALL_SECONDS", "210")),
            max_turns=int(os.getenv("MAX_TURNS", "12")),
        )


def get_required_env_value(name):
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value
