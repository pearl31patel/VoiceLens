import argparse
import time

from callerbot.config import Settings
from callerbot.scenarios import SCENARIOS
from callerbot.storage import CallStore
from callerbot.twilio_client import TwilioDialer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PG AI voice bot assessment calls.")
    parser.add_argument("--count", type=int, default=10, help="Number of scenarios to call.")
    parser.add_argument("--scenario", type=str, default=None, help="Run one scenario by id.")
    parser.add_argument("--gap-seconds", type=int, default=20, help="Wait between calls.")
    args = parser.parse_args()

    settings = Settings.from_env()
    store = CallStore(settings.call_output_dir)
    dialer = TwilioDialer(settings)

    if args.scenario:
        scenarios = [s for s in SCENARIOS if s.id == args.scenario]
        if not scenarios:
            raise SystemExit(f"Unknown scenario id: {args.scenario}")
    else:
        scenarios = SCENARIOS[: args.count]

    print(f"Running {len(scenarios)} call(s).")
    print(f"Target number: {settings.assessment_number}")
    print("Output folder:", settings.call_output_dir)

    for index, scenario in enumerate(scenarios, start=1):
        session_id = store.create_session(scenario)
        print(f"\n[{index}/{len(scenarios)}] Calling scenario '{scenario.id}'")
        print("Session:", session_id)

        call_sid = dialer.start_call(session_id=session_id, scenario_id=scenario.id)
        store.update_metadata(session_id, {"twilio_call_sid": call_sid})
        print("Twilio call SID:", call_sid)

        if index < len(scenarios):
            time.sleep(args.gap_seconds)

    print("\nCalls started. Recordings will arrive through the recording callback after Twilio finishes processing them.")
    print("After calls complete, run:")
    print("python -m callerbot.analyzer --calls data/calls --out BUG_REPORT.md")


if __name__ == "__main__":
    main()
