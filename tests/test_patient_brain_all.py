import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from callerbot.config import Settings
from callerbot.llm_patient import PatientBrain
from callerbot.scenarios import SCENARIOS


def normalize(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def contains_all(actual: str, expected_items: list[str]) -> bool:
    actual_norm = normalize(actual)
    return all(normalize(item) in actual_norm for item in expected_items)


def contains_none(actual: str, forbidden_items: list[str]) -> bool:
    actual_norm = normalize(actual)
    return all(normalize(item) not in actual_norm for item in forbidden_items)


def run_case(
    brain,
    scenario,
    title,
    agent_text,
    must=None,
    forbidden=None,
    done=None,
    turn_count=1,
    transcript=None,
):
    must = must or []
    forbidden = forbidden or []

    if transcript is None:
        transcript = [("AGENT", agent_text)]

    reply = brain.next_reply(
        scenario=scenario,
        transcript=transcript,
        latest_agent_text=agent_text,
        turn_count=turn_count,
    )

    passed = True

    if must:
        passed = passed and contains_all(reply.say, must)

    if forbidden:
        passed = passed and contains_none(reply.say, forbidden)

    if done is not None:
        passed = passed and reply.done == done

    status = "PASS" if passed else "FAIL"

    print("=" * 100)
    print(f"{status}: {title}")
    print("SCENARIO:", scenario.id, "|", scenario.patient_name)
    print("AGENT:  ", agent_text)
    print("PATIENT:", reply.say)
    print("DONE:   ", reply.done)

    if must:
        print("MUST CONTAIN:", must)

    if forbidden:
        print("MUST NOT CONTAIN:", forbidden)

    if done is not None:
        print("EXPECTED DONE:", done)

    print()

    return passed


settings = Settings.from_env()
brain = PatientBrain(settings)
scenario_by_id = {scenario.id: scenario for scenario in SCENARIOS}

passed = 0
total = 0


def test(title, scenario, agent_text, must=None, forbidden=None, done=None, turn_count=1, transcript=None):
    global passed, total
    total += 1

    ok = run_case(
        brain=brain,
        scenario=scenario,
        title=title,
        agent_text=agent_text,
        must=must,
        forbidden=forbidden,
        done=done,
        turn_count=turn_count,
        transcript=transcript,
    )

    if ok:
        passed += 1


# ============================================================
# 1. DETERMINISTIC PROFILE TESTS
# ============================================================

print("\n" + "#" * 100)
print("1. DETERMINISTIC PROFILE TESTS")
print("#" * 100)

for scenario in SCENARIOS:
    total += 1
    profile = brain._build_profile(scenario)

    ok = True
    ok = ok and profile["name"] == scenario.patient_name
    ok = ok and profile["first_name"] == scenario.patient_name.split()[0]
    ok = ok and len(profile["phone_digits"]) >= 7
    ok = ok and "@" in profile["email"]
    ok = ok and profile["name_spelling"]

    status = "PASS" if ok else "FAIL"
    print("=" * 100)
    print(f"{status}: Profile build for {scenario.id}")
    print(profile)
    print()

    if ok:
        passed += 1


# ============================================================
# 2. CORE IDENTITY TESTS
# ============================================================

print("\n" + "#" * 100)
print("2. CORE IDENTITY TESTS")
print("#" * 100)

s0 = SCENARIOS[0]
p0 = brain._build_profile(s0)

test(
    "Wrong old patient name correction",
    s0,
    "Am I speaking with Maya?",
    must=["No", p0["name"]],
    forbidden=["Yes"],
    done=False,
)

test(
    "Correct first name confirmation",
    s0,
    f"Am I speaking with {p0['first_name']}?",
    must=["Yes", p0["first_name"]],
    done=False,
)

test(
    "Correct full name confirmation",
    s0,
    f"Am I speaking with {p0['name']}?",
    must=["Yes"],
    done=False,
)

test(
    "DOB only",
    s0,
    "Please provide your date of birth.",
    must=[p0["dob_speaking"]],
    forbidden=[p0["name"]],
    done=False,
)

test(
    "Full name only",
    s0,
    "Please tell me your full name.",
    must=[p0["name"]],
    forbidden=[p0["dob_speaking"]],
    done=False,
)

test(
    "Full name and DOB together",
    s0,
    "Please tell me your full name and date of birth.",
    must=[p0["name"], p0["dob_speaking"]],
    done=False,
)

test(
    "Full name and DOB with patient first name",
    s0,
    f"Please provide {p0['first_name']}'s full name and date of birth.",
    must=[p0["name"], p0["dob_speaking"]],
    done=False,
)

test(
    "Spell first and last name",
    s0,
    "Can you please spell your first and last name to confirm?",
    must=[p0["name_spelling"]],
    done=False,
)

test(
    "Confirm name DOB and spell name",
    s0,
    f"I have your name as {p0['name']}, and your date of birth as {p0['dob_display']}. Is that correct? If so, please spell your first and last name.",
    must=["Yes", "correct", p0["name_spelling"]],
    done=False,
)

test(
    "Confirm name and DOB only",
    s0,
    f"I have your name as {p0['name']}, and your date of birth as {p0['dob_display']}. Is that correct?",
    must=["Yes", "correct"],
    forbidden=[p0["name_spelling"], "phone number", "not correct"],
    done=False,
)


# ============================================================
# 3. PHONE TESTS
# ============================================================

print("\n" + "#" * 100)
print("3. PHONE TESTS")
print("#" * 100)

test(
    "Correct phone confirmation display format",
    s0,
    f"I have your phone number as {p0['phone_display']} and your date of birth as {p0['dob_display']}. Is that correct?",
    must=["Yes", "correct"],
    forbidden=["not correct"],
    done=False,
)

test(
    "Correct phone confirmation parentheses format",
    s0,
    "I have your phone number as (805) 555-0142 and your date of birth as 04/18/1991. Is that correct?",
    must=["Yes", "correct"],
    forbidden=["not correct"],
    done=False,
)

test(
    "Wrong phone confirmation short number",
    s0,
    "I have your phone number as 805550142, and your date of birth as 04/18/1991. Is that correct?",
    must=["No", "phone number", "not correct"],
    done=False,
)

test(
    "Wrong phone confirmation different number",
    s0,
    "I have your phone number as 805-111-2222 and your date of birth as 04/18/1991. Is that correct?",
    must=["No", "phone number", "not correct"],
    done=False,
)

test(
    "Phone number request",
    s0,
    "Please tell me the phone number you have on file.",
    must=[p0["phone_speaking"]],
    done=False,
)

test(
    "Phone lookup request",
    s0,
    "Would you like to use your phone number to look up your record? If so, please provide the number you have on file.",
    must=[p0["phone_speaking"]],
    done=False,
)


# ============================================================
# 4. APPOINTMENT SIMPLE FLOW
# ============================================================

print("\n" + "#" * 100)
print("4. APPOINTMENT SIMPLE FLOW")
print("#" * 100)

test(
    "Appointment simple start",
    s0,
    "How can I help you today?",
    must=["appointment", "sore throat"],
    done=False,
)

test(
    "Appointment asks preferred time",
    s0,
    "What day or time works best for you?",
    must=["tomorrow"],
    done=False,
)

test(
    "Preferred time unavailable",
    s0,
    "Tomorrow morning is not available. We have Monday morning openings.",
    must=["Monday"],
    done=False,
)

test(
    "Appointment offer accepted",
    s0,
    "Monday has 9 AM with Doctor Kelly Noble. Would you like that?",
    must=["Yes"],
    done=False,
)

test(
    "Appointment booking confirmation",
    s0,
    "Just to confirm, Monday June 22 at 9 AM. Should I book it?",
    must=["Yes"],
    done=False,
)

test(
    "Appointment booked",
    s0,
    "Your appointment is booked for Monday June 22 at 9 AM.",
    must=["thank"],
)


# ============================================================
# 5. CALL ENDING TESTS
# ============================================================

print("\n" + "#" * 100)
print("5. CALL ENDING TESTS")
print("#" * 100)

test(
    "Transfer to representative",
    s0,
    "Connecting you to a representative. Please wait.",
    must=["Okay", "thank"],
    done=True,
)

test(
    "Transfer to patient support",
    s0,
    "I will route you to patient support now.",
    must=["Okay", "thank"],
    done=True,
)

test(
    "Goodbye ending",
    s0,
    "Goodbye.",
    must=["Okay", "thank"],
    done=True,
)

test(
    "PG AI goodbye line",
    s0,
    "Hello. You've reached the Pretty Good AI test line. Goodbye.",
    must=["Okay", "thank"],
    done=True,
)

test(
    "Max turns reached",
    s0,
    "Can you repeat that?",
    must=["thank", "go"],
    done=True,
    turn_count=settings.max_turns,
)


# ============================================================
# 6. ALL SCENARIO IDENTITY MATRIX
# ============================================================

print("\n" + "#" * 100)
print("6. ALL SCENARIO IDENTITY MATRIX")
print("#" * 100)

for scenario in SCENARIOS:
    profile = brain._build_profile(scenario)

    test(
        f"{scenario.id}: correct first name",
        scenario,
        f"Am I speaking with {profile['first_name']}?",
        must=["Yes", profile["first_name"]],
        done=False,
    )

    test(
        f"{scenario.id}: wrong old name Maya",
        scenario,
        "Am I speaking with Maya?",
        must=["No", profile["name"]],
        forbidden=["Yes"],
        done=False,
    )

    test(
        f"{scenario.id}: DOB only",
        scenario,
        "Please provide your date of birth.",
        must=[profile["dob_speaking"]],
        done=False,
    )

    test(
        f"{scenario.id}: full name only",
        scenario,
        "Please tell me your full name.",
        must=[profile["name"]],
        done=False,
    )

    test(
        f"{scenario.id}: full name and DOB",
        scenario,
        "Please tell me your full name and date of birth.",
        must=[profile["name"], profile["dob_speaking"]],
        done=False,
    )

    test(
        f"{scenario.id}: spell name",
        scenario,
        "Please spell your first and last name.",
        must=[profile["name_spelling"]],
        done=False,
    )


# ============================================================
# 7. SCENARIO-SPECIFIC TESTS
# ============================================================

print("\n" + "#" * 100)
print("7. SCENARIO-SPECIFIC TESTS")
print("#" * 100)

test(
    "appt_reschedule: start request",
    scenario_by_id["appt_reschedule"],
    "How can I help you today?",
    must=["reschedule"],
    done=False,
)

test(
    "appt_reschedule: existing appointment",
    scenario_by_id["appt_reschedule"],
    "What appointment do you want to change?",
    must=["Tuesday", "2"],
    done=False,
)

test(
    "appt_reschedule: preferred new time",
    scenario_by_id["appt_reschedule"],
    "What time would you like to move it to?",
    must=["Friday"],
    done=False,
)

test(
    "appt_reschedule: confirm new time",
    scenario_by_id["appt_reschedule"],
    "I can move it to Friday afternoon. Is that okay?",
    must=["Yes"],
    done=False,
)

test(
    "appt_cancel: start request",
    scenario_by_id["appt_cancel"],
    "How can I help you today?",
    must=["cancel"],
    done=False,
)

test(
    "appt_cancel: cancellation fee question",
    scenario_by_id["appt_cancel"],
    "Your appointment has been cancelled.",
    must=["fee"],
    done=False,
)

test(
    "refill_normal: start request",
    scenario_by_id["refill_normal"],
    "How can I help you today?",
    must=["refill"],
    done=False,
)

test(
    "refill_normal: medication name",
    scenario_by_id["refill_normal"],
    "What medication do you need refilled?",
    must=["lisinopril"],
    done=False,
)

test(
    "refill_normal: medication dose",
    scenario_by_id["refill_normal"],
    "What dose are you taking?",
    must=["10"],
    done=False,
)

test(
    "refill_normal: pharmacy",
    scenario_by_id["refill_normal"],
    "What pharmacy do you use?",
    must=["CVS", "State"],
    done=False,
)

test(
    "refill_normal: pills left",
    scenario_by_id["refill_normal"],
    "How many pills do you have left?",
    must=["two"],
    done=False,
)

test(
    "office_info: start request",
    scenario_by_id["office_info"],
    "How can I help you today?",
    must=["office"],
    done=False,
)

test(
    "office_info: Saturday and parking",
    scenario_by_id["office_info"],
    "What office information do you need?",
    must=["Saturday", "parking"],
    done=False,
)

test(
    "office_info: repeat address",
    scenario_by_id["office_info"],
    "The address is on State Street.",
    must=["address"],
    done=False,
)

test(
    "insurance_question: start request",
    scenario_by_id["insurance_question"],
    "How can I help you today?",
    must=["Aetna"],
    done=False,
)

test(
    "insurance_question: PPO detail",
    scenario_by_id["insurance_question"],
    "What type of insurance plan do you have?",
    must=["Aetna", "PPO"],
    done=False,
)

test(
    "insurance_question: coverage question",
    scenario_by_id["insurance_question"],
    "We accept Aetna PPO.",
    must=["covered"],
    done=False,
)

test(
    "weekend_edge: Sunday request",
    scenario_by_id["weekend_edge"],
    "How can I help you today?",
    must=["Sunday"],
    done=False,
)

test(
    "weekend_edge: closed Sunday accept Monday",
    scenario_by_id["weekend_edge"],
    "We are closed Sunday. Monday morning is available.",
    must=["Monday"],
    done=False,
)

test(
    "emergency_edge: start emergency symptoms",
    scenario_by_id["emergency_edge"],
    "How can I help you today?",
    must=["chest", "shortness"],
    done=False,
)

test(
    "emergency_edge: pain details",
    scenario_by_id["emergency_edge"],
    "Can you describe your symptoms?",
    must=["chest", "shortness", "left arm"],
    done=False,
)

test(
    "emergency_edge: emergency guidance accepted",
    scenario_by_id["emergency_edge"],
    "You should call 911 or go to the emergency room now.",
    must=["Okay"],
    done=True,
)

test(
    "controlled_refill_edge: start request",
    scenario_by_id["controlled_refill_edge"],
    "How can I help you today?",
    must=["oxycodone"],
    done=False,
)

test(
    "controlled_refill_edge: lost bottle detail",
    scenario_by_id["controlled_refill_edge"],
    "Why do you need the refill early?",
    must=["lost", "travel"],
    done=False,
)

test(
    "controlled_refill_edge: asks if allowed",
    scenario_by_id["controlled_refill_edge"],
    "I can send the refill immediately.",
    must=["allowed"],
    done=False,
)

test(
    "unclear_interruption: unclear start",
    scenario_by_id["unclear_interruption"],
    "How can I help you today?",
    must=["doctor"],
    done=False,
)

test(
    "unclear_interruption: clarify rash",
    scenario_by_id["unclear_interruption"],
    "Can you clarify what you need help with?",
    must=["rash", "visit"],
    done=False,
)

test(
    "fax_status: start request",
    scenario_by_id["fax_status"],
    "How can I help you today?",
    must=["fax"],
    done=False,
)

test(
    "fax_status: cardiology records",
    scenario_by_id["fax_status"],
    "What fax are you asking about?",
    must=["cardiology"],
    done=False,
)

test(
    "privacy_edge: spouse lab request",
    scenario_by_id["privacy_edge"],
    "How can I help you today?",
    must=["spouse", "lab"],
    done=False,
)

test(
    "privacy_edge: spouse name",
    scenario_by_id["privacy_edge"],
    "Whose lab results are you asking about?",
    must=["Alex"],
    done=False,
)

test(
    "privacy_edge: authorization question",
    scenario_by_id["privacy_edge"],
    "Are you authorized to receive your spouse's medical information?",
    must=["not sure"],
    done=False,
)


# ============================================================
# 8. MULTI-TURN CONTEXT TESTS
# ============================================================

print("\n" + "#" * 100)
print("8. MULTI-TURN CONTEXT TESTS")
print("#" * 100)

test(
    "Multi-turn appointment context",
    s0,
    "What day or time works best for you?",
    must=["tomorrow"],
    done=False,
    transcript=[
        ("AGENT", "How can I help you today?"),
        ("PATIENT", "I need to book an appointment for a sore throat."),
        ("AGENT", "What day or time works best for you?"),
    ],
)

test(
    "Multi-turn refill context",
    scenario_by_id["refill_normal"],
    "What pharmacy do you use?",
    must=["CVS", "State"],
    done=False,
    transcript=[
        ("AGENT", "How can I help you today?"),
        ("PATIENT", "I need a refill for lisinopril."),
        ("AGENT", "What dose are you taking?"),
        ("PATIENT", "10 mg once daily."),
        ("AGENT", "What pharmacy do you use?"),
    ],
)

test(
    "Multi-turn reschedule context",
    scenario_by_id["appt_reschedule"],
    "Would Friday afternoon work?",
    must=["Yes", "Friday"],
    done=False,
    transcript=[
        ("AGENT", "How can I help you today?"),
        ("PATIENT", "I need to reschedule my appointment."),
        ("AGENT", "What time would you prefer?"),
        ("PATIENT", "Friday afternoon if possible."),
        ("AGENT", "Would Friday afternoon work?"),
    ],
)


# ============================================================
# FINAL RESULT
# ============================================================

print("=" * 100)
print(f"FINAL RESULT: {passed}/{total} passed")
print("=" * 100)

if passed == total:
    print("All major tests passed.")
else:
    print("Some tests failed. Review the FAIL items above and tune prompt/cleanup.")