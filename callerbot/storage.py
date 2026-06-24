import json
from datetime import datetime
from pathlib import Path


class CallStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_session(self, scenario):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}_{scenario.id}"

        folder = self.session_dir(session_id)
        folder.mkdir(parents=True, exist_ok=True)

        self.write_json(
            session_id,
            "metadata.json",
            {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "scenario": self.make_scenario_data(scenario),
                "twilio_call_sid": None,
                "recording_url": None,
                "recording_path": None,
            },
        )

        (folder / "transcript.txt").write_text("", encoding="utf-8")
        (folder / "events.jsonl").write_text("", encoding="utf-8")

        return session_id

    def session_dir(self, session_id):
        return self.root / session_id

    def write_json(self, session_id, filename, data):
        path = self.session_dir(session_id) / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read_json(self, session_id, filename):
        path = self.session_dir(session_id) / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def update_metadata(self, session_id, updates):
        metadata = self.read_json(session_id, "metadata.json")
        metadata.update(updates)
        self.write_json(session_id, "metadata.json", metadata)

    def append_event(self, session_id, event):
        path = self.session_dir(session_id) / "events.jsonl"

        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_transcript(self, session_id, speaker, text):
        clean_text = self.clean_text(text)

        if not clean_text:
            return

        path = self.session_dir(session_id) / "transcript.txt"

        with path.open("a", encoding="utf-8") as file:
            file.write(f"{speaker.upper()}: {clean_text}\n\n")

    def make_scenario_data(self, scenario):
        return {
            "id": scenario.id,
            "title": scenario.title,
            "patient_name": scenario.patient_name,
            "dob": scenario.dob,
            "opening_goal": scenario.opening_goal,
            "details": scenario.details,
            "success_criteria": scenario.success_criteria,
            "edge_case": scenario.edge_case,
        }

    def clean_text(self, text):
        return " ".join(text.strip().split())