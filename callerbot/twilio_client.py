from twilio.rest import Client

from callerbot.config import Settings


class TwilioDialer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    def start_call(self, session_id: str, scenario_id: str) -> str:
        target = self.settings.assessment_number
        if target != "+18054398008":
            raise RuntimeError(f"Refusing to call non-assessment number: {target}")

        twiml_url = (
            f"{self.settings.public_base_url}/twiml"
            f"?session_id={session_id}&scenario_id={scenario_id}"
        )

        call = self.client.calls.create(
            to=target,
            from_=self.settings.twilio_from_number,
            url=twiml_url,
            method="POST",
            record=True,
            recording_channels="dual",
            recording_status_callback=f"{self.settings.public_base_url}/recording-callback",
            recording_status_callback_method="POST",
            status_callback=f"{self.settings.public_base_url}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
            timeout=30,
        )
        return call.sid
