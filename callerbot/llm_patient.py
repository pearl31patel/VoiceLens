import json
import os
import re
import time
from datetime import datetime

from openai import OpenAI


class PatientReply:
    def __init__(self, say, done, reason=""):
        self.say = say
        self.done = done
        self.reason = reason


class PatientBrain:
    def __init__(self, settings):
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self.last_request_at = 0.0
        self.min_seconds_between_llm_calls = 0.15

    def next_reply(self, scenario, transcript, latest_agent_text, turn_count):
        if turn_count >= self.settings.max_turns:
            return PatientReply(
                say="Okay, thank you. I have to go now.",
                done=True,
                reason="max turns reached",
            )

        self.wait_before_llm_call()
        profile = self.build_patient_profile(scenario)

        guardrail_reply = self.handle_basic_rules(
            scenario=scenario,
            profile=profile,
            latest_agent_text=latest_agent_text,
            transcript=transcript,
        )

        if guardrail_reply is not None:
            return guardrail_reply

        messages = [
            {
                "role": "system",
                "content": self.make_system_prompt(),
            },
            {
                "role": "user",
                "content": self.make_case_prompt(
                    scenario=scenario,
                    profile=profile,
                    transcript=transcript,
                    latest_agent_text=latest_agent_text,
                    turn_count=turn_count,
                ),
            },
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=0.02,
                max_tokens=80,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content or "{}"
            data = json.loads(self.clean_json_text(raw))

            say = str(data.get("say", "")).strip()
            done = bool(data.get("done", False))
            reason = str(data.get("reason", "")).strip()

            if not say:
                say = "Sorry, could you repeat that?"

            say = self.clean_patient_reply(
                text=say,
                profile=profile,
                latest_agent_text=latest_agent_text,
            )

            return PatientReply(say=say, done=done, reason=reason)

        except Exception as exc:
            print("[patient-brain] LLM failed:", repr(exc))
            return PatientReply(
                say="Sorry, could you repeat that?",
                done=False,
                reason=f"fallback after LLM error: {exc}",
            )

    def wait_before_llm_call(self):
        elapsed = time.monotonic() - self.last_request_at

        if elapsed < self.min_seconds_between_llm_calls:
            time.sleep(self.min_seconds_between_llm_calls - elapsed)

        self.last_request_at = time.monotonic()

    def build_patient_profile(self, scenario):
        name = scenario.patient_name.strip()
        first_name = name.split()[0] if name else "the patient"

        dob_display = scenario.dob.strip()
        dob_speaking = self.speak_date_of_birth(dob_display)

        phone_display = os.getenv("PATIENT_PHONE", "805-555-0142").strip()
        phone_digits = self.keep_digits_only(phone_display)
        phone_speaking = self.speak_phone_number(phone_display)

        email = os.getenv(
            "PATIENT_EMAIL",
            self.make_default_email_from_name(name),
        ).strip()

        address = os.getenv(
            "PATIENT_ADDRESS",
            "123 Oak Street, Santa Barbara, CA",
        ).strip()

        return {
            "name": name,
            "first_name": first_name,
            "name_spelling": self.spell_patient_name(name),
            "dob_display": dob_display,
            "dob_speaking": dob_speaking,
            "phone_display": phone_display,
            "phone_digits": phone_digits,
            "phone_speaking": phone_speaking,
            "email": email,
            "address": address,
        }

    def handle_basic_rules(self, scenario, profile, latest_agent_text, transcript):
        lower = latest_agent_text.lower()
        scenario_text = f"{scenario.opening_goal} {scenario.details}".lower()
        analysis = self.understand_agent_message(latest_agent_text, profile).lower()

        if (
            "has_phone_reference: yes" in analysis
            and "phone_match: yes" in analysis
            and "asks_confirmation: yes" in analysis
        ):
            return PatientReply(
                say="Yes, that’s correct.",
                done=False,
                reason="dynamic correct phone confirmation",
            )

        if (
            "has_phone_reference: yes" in analysis
            and "phone_match: no" in analysis
            and "asks_confirmation: yes" in analysis
        ):
            return PatientReply(
                say=f"No, that phone number is not correct. My phone number is {profile['phone_speaking']}.",
                done=False,
                reason="dynamic wrong phone confirmation",
            )

        if any(
            phrase in lower
            for phrase in [
                "goodbye",
                "connect",
                "transfer",
                "representative",
                "patient support",
                "route you",
            ]
        ):
            return PatientReply(
                say="Okay, thank you.",
                done=True,
                reason="dynamic call ending",
            )

        if any(
            phrase in lower
            for phrase in [
                "call 911",
                "go to the emergency room",
                "go to emergency",
                "go to the er",
                "seek emergency",
            ]
        ):
            return PatientReply(
                say="Okay, I’ll do that now. Thank you.",
                done=True,
                reason="dynamic emergency guidance accepted",
            )

        if "am i speaking with" in lower or "is this" in lower:
            first_name = profile["first_name"].lower()
            full_name = profile["name"].lower()

            if first_name in lower or full_name in lower:
                return PatientReply(
                    say=f"Yes, I am {profile['first_name']}.",
                    done=False,
                    reason="dynamic correct identity confirmation",
                )

            return PatientReply(
                say=f"No, this is {profile['name']}.",
                done=False,
                reason="dynamic wrong identity correction",
            )

        if self.agent_asks_to_spell_name(lower):
            if "is that correct" in lower:
                return PatientReply(
                    say=f"Yes, that’s correct. {profile['name_spelling']}.",
                    done=False,
                    reason="dynamic name confirmation and spelling",
                )

            return PatientReply(
                say=f"{profile['name_spelling']}.",
                done=False,
                reason="dynamic name spelling",
            )

        if self.agent_asks_for_full_name_and_dob(lower):
            return PatientReply(
                say=f"{profile['name']}, {profile['dob_speaking']}.",
                done=False,
                reason="dynamic full name and DOB",
            )

        if (
            self.agent_asks_for_dob(lower)
            and "phone" not in lower
            and "number" not in lower
            and "full name" not in lower
            and not self.agent_asks_to_spell_name(lower)
        ):
            return PatientReply(
                say=f"{profile['dob_speaking']}.",
                done=False,
                reason="dynamic DOB only",
            )

        if "full name" in lower and not self.agent_asks_for_dob(lower):
            return PatientReply(
                say=profile["name"],
                done=False,
                reason="dynamic full name only",
            )

        if self.agent_asks_for_phone(lower):
            return PatientReply(
                say=f"{profile['phone_speaking']}.",
                done=False,
                reason="dynamic phone request",
            )

        if any(word in lower for word in ["not available", "unavailable", "closed"]):
            offered_time = self.find_offered_time(latest_agent_text)

            if offered_time:
                return PatientReply(
                    say=f"Yes, {offered_time} works.",
                    done=False,
                    reason="dynamic accepted next available option",
                )

        if any(
            phrase in lower
            for phrase in [
                "would you like that",
                "should i book",
                "is that okay",
                "would that work",
                "does that work",
            ]
        ):
            if "send the refill immediately" in lower or (
                "refill" in lower and "immediately" in lower
            ):
                if "allowed" in scenario_text:
                    return PatientReply(
                        say="Is that allowed?",
                        done=False,
                        reason="dynamic controlled refill safety question",
                    )

            return PatientReply(
                say="Yes, that works.",
                done=False,
                reason="dynamic offer accepted",
            )

        if any(word in lower for word in ["booked", "scheduled", "confirmed"]):
            if "appointment" in lower or "visit" in lower:
                return PatientReply(
                    say="Thank you.",
                    done=True,
                    reason="dynamic appointment completed",
                )

        if "cancelled" in lower or "canceled" in lower:
            if "fee" in scenario_text:
                return PatientReply(
                    say="Thank you. Is there a cancellation fee?",
                    done=False,
                    reason="dynamic cancellation fee question",
                )

            return PatientReply(
                say="Thank you.",
                done=True,
                reason="dynamic cancellation completed",
            )

        if self.agent_asks_how_can_help(lower):
            return PatientReply(
                say=self.make_opening_reply_from_scenario(scenario),
                done=False,
                reason="dynamic opening from scenario goal",
            )

        if any(
            phrase in lower
            for phrase in [
                "what day",
                "what time",
                "time works best",
                "day or time",
                "preferred time",
            ]
        ):
            preferred_time = self.find_preferred_time_from_details(scenario.details)

            if preferred_time:
                return PatientReply(
                    say=f"{preferred_time} works best.",
                    done=False,
                    reason="dynamic preferred time",
                )

        if "pharmacy" in lower:
            pharmacy = self.find_sentence_from_details(scenario.details, ["pharmacy", "cvs"])

            if pharmacy:
                pharmacy = pharmacy.replace("Preferred pharmacy is ", "")
                return PatientReply(
                    say=f"{pharmacy}.",
                    done=False,
                    reason="dynamic pharmacy answer",
                )

        if "medication" in lower and "refill" in scenario_text:
            medication = self.find_sentence_from_details(scenario.details, ["medication is"])

            if medication:
                medication = medication.replace("Medication is ", "")
                return PatientReply(
                    say=f"{medication}.",
                    done=False,
                    reason="dynamic medication answer",
                )

        if "dose" in lower or "taking" in lower:
            medication = self.find_sentence_from_details(scenario.details, ["mg", "daily"])

            if medication:
                medication = medication.replace("Medication is ", "")
                return PatientReply(
                    say=f"{medication}.",
                    done=False,
                    reason="dynamic dose answer",
                )

        if "how many pills" in lower or "pills left" in lower:
            pills = self.find_sentence_from_details(scenario.details, ["pills left"])

            if pills:
                return PatientReply(
                    say=pills + ".",
                    done=False,
                    reason="dynamic pills-left answer",
                )

        if "office information" in lower or (
            "office" in lower and "need" in lower
        ):
            office_info = self.find_sentence_from_details(
                scenario.details,
                ["saturday", "parking"],
            )

            if office_info:
                return PatientReply(
                    say=office_info + ".",
                    done=False,
                    reason="dynamic office info answer",
                )

        if "insurance plan" in lower or "type of insurance" in lower:
            insurance = self.find_sentence_from_details(scenario.details, ["aetna", "ppo"])

            if insurance:
                return PatientReply(
                    say=insurance.replace("You have ", "I have ") + ".",
                    done=False,
                    reason="dynamic insurance plan answer",
                )

        if "accept" in lower and "aetna" in lower:
            return PatientReply(
                say="Will my visit be fully covered?",
                done=False,
                reason="dynamic insurance coverage question",
            )

        if "describe your symptoms" in lower or "symptoms" in lower:
            symptoms = self.find_sentence_from_details(
                scenario.details,
                ["chest pain", "shortness", "left arm"],
            )

            if symptoms:
                return PatientReply(
                    say=symptoms + ".",
                    done=False,
                    reason="dynamic symptom detail answer",
                )

        if "why" in lower and "refill" in lower:
            reason = self.find_sentence_from_details(scenario.details, ["lost", "traveling"])

            if reason:
                return PatientReply(
                    say=reason + ".",
                    done=False,
                    reason="dynamic early refill reason",
                )

        if "send the refill immediately" in lower or (
            "refill" in lower and "immediately" in lower
        ):
            if "allowed" in scenario_text:
                return PatientReply(
                    say="Is that allowed?",
                    done=False,
                    reason="dynamic controlled refill allowed question",
                )

        if "clarify" in lower or "what do you need help with" in lower:
            rash = self.find_sentence_from_details(scenario.details, ["rash", "visit"])

            if rash:
                return PatientReply(
                    say="Sorry, I mean I need to book a visit for a rash.",
                    done=False,
                    reason="dynamic clarification from scenario",
                )

        if "what fax" in lower or "which fax" in lower:
            fax = self.find_sentence_from_details(scenario.details, ["cardiology", "fax"])

            if fax:
                return PatientReply(
                    say=fax + ".",
                    done=False,
                    reason="dynamic fax detail",
                )

        if "whose lab" in lower or "whose results" in lower:
            spouse = self.find_sentence_from_details(scenario.details, ["spouse", "alex"])

            if spouse:
                return PatientReply(
                    say="I’m calling for my spouse, Alex Bennett.",
                    done=False,
                    reason="dynamic spouse answer",
                )

        if "authorized" in lower or "authorization" in lower:
            if "not sure" in scenario_text:
                return PatientReply(
                    say="I’m not sure.",
                    done=False,
                    reason="dynamic authorization answer",
                )

        return None

    def agent_asks_for_full_name_and_dob(self, lower):
        return "full name" in lower and self.agent_asks_for_dob(lower)

    def agent_asks_for_dob(self, lower):
        return any(
            phrase in lower
            for phrase in [
                "date of birth",
                "dob",
                "birth date",
                "birthday",
            ]
        )

    def agent_asks_for_phone(self, lower):
        if "phone" not in lower and "number on file" not in lower:
            return False

        return any(
            phrase in lower
            for phrase in [
                "phone number",
                "number on file",
                "provide the number",
                "tell me the number",
                "tell me your phone",
                "provide your phone",
                "look up your record",
            ]
        )

    def agent_asks_to_spell_name(self, lower):
        ask_phrases = [
            "please spell",
            "could you please spell",
            "can you please spell",
            "spell your",
            "spell first",
            "spell last",
            "spelling them out",
        ]

        thanks_phrases = [
            "thank you for spelling",
            "thanks for spelling",
        ]

        if any(phrase in lower for phrase in thanks_phrases):
            return False

        return any(phrase in lower for phrase in ask_phrases)

    def agent_asks_how_can_help(self, lower):
        return any(
            phrase in lower
            for phrase in [
                "how can i help",
                "how may i help",
                "what can i help",
                "what do you need help with today",
            ]
        )

    def make_opening_reply_from_scenario(self, scenario):
        goal = scenario.opening_goal.strip().rstrip(".")
        details = scenario.details.strip()

        if "Begin with:" in details:
            match = re.search(r"Begin with:\s*['\"](.+?)['\"]", details)
            if match:
                return match.group(1)

        medication = self.find_sentence_from_details(details, ["medication is"])

        if medication and "refill" in goal.lower():
            medication = medication.replace("Medication is ", "")
            return f"I need a refill for {medication}."

        emergency = self.find_sentence_from_details(
            details,
            ["chest pain", "shortness", "left arm"],
        )

        if emergency:
            return emergency + "."

        if goal.lower().startswith("book"):
            return f"I’d like to {goal[0].lower() + goal[1:]}."

        if goal.lower().startswith("try"):
            return f"I’d like to {goal[0].lower() + goal[1:]}."

        if goal.lower().startswith("ask"):
            return f"I’d like to {goal[0].lower() + goal[1:]}."

        if goal.lower().startswith("reschedule"):
            return "I’d like to reschedule an existing appointment."

        if goal.lower().startswith("cancel"):
            return "I’d like to cancel my appointment."

        return f"I’d like to {goal[0].lower() + goal[1:]}."

    def find_preferred_time_from_details(self, details):
        patterns = [
            r"tomorrow morning after\s+\d+\s*[AP]M",
            r"friday afternoon",
            r"sunday at\s+\d+\s*[AP]M",
            r"monday morning",
        ]

        for pattern in patterns:
            match = re.search(pattern, details, flags=re.IGNORECASE)

            if match:
                value = match.group(0)
                return value[0].upper() + value[1:]

        return ""

    def find_offered_time(self, text):
        days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

        for day in days:
            match = re.search(
                rf"\b{day}\b[^.?!,]*",
                text,
                flags=re.IGNORECASE,
            )

            if match:
                phrase = match.group(0).strip()
                return phrase[0].upper() + phrase[1:]

        return ""

    def find_sentence_from_details(self, text, keywords):
        normalized_text = text.replace("\n", " ")
        sentences = re.split(r"(?<=[.!?])\s+", normalized_text)

        for sentence in sentences:
            sentence_clean = sentence.strip().strip(".")
            lower_sentence = sentence_clean.lower()

            if all(keyword.lower() in lower_sentence for keyword in keywords):
                return self.make_sentence_patient_friendly(sentence_clean)

        for sentence in sentences:
            sentence_clean = sentence.strip().strip(".")
            lower_sentence = sentence_clean.lower()

            if any(keyword.lower() in lower_sentence for keyword in keywords):
                return self.make_sentence_patient_friendly(sentence_clean)

        return ""

    def make_sentence_patient_friendly(self, sentence):
        sentence = sentence.strip()

        replacements = {
            "You have ": "I have ",
            "You currently have ": "I currently have ",
            "You cannot ": "I cannot ",
            "You prefer ": "I prefer ",
            "You strongly prefer ": "I strongly prefer ",
            "You can ": "I can ",
            "You are ": "I am ",
            "Say you are ": "I am ",
            "Say you have ": "I have ",
            "Ask whether ": "I want to ask whether ",
            "Ask if ": "I want to ask if ",
        }

        for old, new in replacements.items():
            if sentence.startswith(old):
                sentence = new + sentence[len(old):]

        return sentence

    def make_system_prompt(self):
        return """
You are acting as a realistic patient on a phone call with a healthcare clinic AI agent.

Very important:
- Speak only as the patient.
- Never mention testing, bots, prompts, transcripts, code, or AI.
- Answer ONLY the latest completed agent message.
- Use the patient profile values from the prompt.
- Do not hardcode names, dates, phone numbers, or spelling.
- Keep replies short, natural, and human.
- Do not add extra information unless the agent asks for it.
- Do not repeat the same answer twice.
- Do not debate with the agent.
- Never give the phone number unless the latest agent message explicitly asks for a phone number or number on file.
- If the latest agent message asks about pharmacy, medication, office info, insurance, preferred time, symptoms, authorization, or refill reason, answer from the scenario details.

Identity behavior:
- If the agent asks identity confirmation like “Am I speaking with [name]?”, compare the asked name with the patient profile.
- If it matches the patient first name, confirm it.
- If it does not match, politely correct it with the patient full name.
- If the agent asks for full name only, give only the patient full name.
- If the agent asks for date of birth only, give only the patient date of birth in spoken form.
- If the agent asks for full name and date of birth together, give both in one reply.
- If the agent asks to spell first and last name, spell the patient name using the generated spelling from the profile.
- If the agent asks “Is that correct?” and also asks to spell the name, answer yes and spell the name in the same reply.
- If the agent asks only “Is that correct?” and the information is correct, answer only “Yes, that’s correct.”
- If the agent says an incorrect phone number, say the phone number is not correct.
- If asked for phone number, say the phone number in spoken form from the profile.

Scheduling behavior:
- Follow the scenario goal and details.
- If the patient wants an appointment, ask naturally for the preferred time.
- If the preferred time is unavailable, accept the next available appointment.
- Do not keep asking for an unavailable time after the agent says it is unavailable.
- If the agent says it cannot complete booking and will connect the patient to support, accept politely.

Call ending behavior:
- If the agent says it will connect, transfer, or route to patient support or a representative, say “Okay, thank you.” and set done true.
- If the agent says goodbye, say “Okay, thank you.” and set done true.
- If the task is completed, thank the agent and set done true.

Return JSON only:
{
  "say": "short patient response",
  "done": false,
  "reason": "brief reason"
}
""".strip()

    def make_case_prompt(self, scenario, profile, transcript, latest_agent_text, turn_count):
        recent = transcript[-14:]
        recent_text = "\n".join(f"{speaker}: {text}" for speaker, text in recent)
        latest_analysis = self.understand_agent_message(latest_agent_text, profile)

        return f"""
Patient profile:
- Full name: {profile["name"]}
- First name: {profile["first_name"]}
- Name spelling: {profile["name_spelling"]}
- Date of birth for display: {profile["dob_display"]}
- Date of birth for speaking: {profile["dob_speaking"]}
- Phone number for display: {profile["phone_display"]}
- Phone number digits: {profile["phone_digits"]}
- Phone number for speaking: {profile["phone_speaking"]}
- Email: {profile["email"]}
- Address: {profile["address"]}

Scenario:
- Title: {scenario.title}
- Goal: {scenario.opening_goal}
- Details: {scenario.details}
- Success criteria: {scenario.success_criteria}
- Edge case: {scenario.edge_case or "None"}

Conversation so far:
{recent_text or "(empty)"}

Latest completed agent message:
{latest_agent_text}

Dynamic analysis of latest agent message:
{latest_analysis}

Patient turn number:
{turn_count}

Choose the patient's next response.

Follow these dynamic latest-message rules:
1. If latest message asks “Am I speaking with [some name]”:
   - If the asked name matches the patient first name, answer:
     “Yes, I am {profile["first_name"]}.”
   - If the asked name does not match the patient first name, answer:
     “No, this is {profile["name"]}.”

2. If latest message asks only for date of birth, answer only:
   “{profile["dob_speaking"]}.”

3. If latest message asks only for full name, answer only:
   “{profile["name"]}.”

4. If latest message asks for full name and date of birth, answer only:
   “{profile["name"]}, {profile["dob_speaking"]}.”

5. If latest message asks “Is that correct?” and also asks to spell first and last name, answer only:
   “Yes, that’s correct. {profile["name_spelling"]}.”

6. If latest message asks to spell first and last name, answer only:
   “{profile["name_spelling"]}.”

7. If dynamic analysis says has_phone_reference: yes, phone_match: yes, and asks_confirmation: yes, answer only:
   “Yes, that’s correct.”

8. If dynamic analysis says has_phone_reference: yes, phone_match: no, and asks_confirmation: yes, answer only:
   “No, that phone number is not correct.”

9. If latest message asks the patient to provide or tell the phone number, answer only:
   “{profile["phone_speaking"]}.”

10. If latest message says connect, transfer, representative, patient support, or goodbye, answer only:
   “Okay, thank you.”
   and set done true.

11. If latest message asks how the clinic can help, follow the scenario goal naturally.

12. If latest message says the preferred time is unavailable, accept the next available option.

Do not include extra details.
Do not answer old questions.
Do not repeat the previous patient answer.
Use only the dynamic patient profile above.

Return JSON only.
""".strip()

    def clean_json_text(self, raw):
        text = raw.strip()

        if text.startswith("```json"):
            text = text.replace("```json", "", 1).strip()

        if text.startswith("```"):
            text = text.replace("```", "", 1).strip()

        if text.endswith("```"):
            text = text[:-3].strip()

        return text

    def clean_patient_reply(self, text, profile, latest_agent_text):
        text = " ".join(text.strip().split())
        lower_latest = latest_agent_text.lower()
        lower_text = text.lower()

        analysis = self.understand_agent_message(latest_agent_text, profile).lower()

        if self.agent_asks_to_spell_name(lower_latest):
            if "is that correct" in lower_latest:
                return f"Yes, that’s correct. {profile['name_spelling']}."
            return f"{profile['name_spelling']}."

        if (
            "phone" not in lower_latest
            and "is that correct" in lower_latest
            and "not correct" in lower_text
        ):
            return "Yes, that’s correct."

        if (
            "has_phone_reference: yes" in analysis
            and "phone_match: yes" in analysis
            and "asks_confirmation: yes" in analysis
            and "not correct" in lower_text
        ):
            return "Yes, that’s correct."

        if (
            "has_phone_reference: yes" in analysis
            and "phone_match: no" in analysis
            and "asks_confirmation: yes" in analysis
        ):
            return "No, that phone number is not correct."

        bad_phrases = [
            "I would like to use my phone number to book an appointment",
            "I'd like to use my phone number to book an appointment",
        ]

        for phrase in bad_phrases:
            if phrase.lower() in lower_text:
                return profile["phone_speaking"]

        return text

    def spell_patient_name(self, name):
        words = name.strip().split()
        spelled_words = []

        for word in words:
            letters = [char.upper() for char in word if char.isalpha()]

            if letters:
                spelled_words.append(", ".join(letters))

        return ". ".join(spelled_words)

    def speak_phone_number(self, phone):
        digits = self.keep_digits_only(phone)

        digit_words = {
            "0": "zero",
            "1": "one",
            "2": "two",
            "3": "three",
            "4": "four",
            "5": "five",
            "6": "six",
            "7": "seven",
            "8": "eight",
            "9": "nine",
        }

        if len(digits) == 10:
            groups = [digits[:3], digits[3:6], digits[6:]]
        else:
            groups = [digits]

        spoken_groups = []

        for group in groups:
            spoken_groups.append(" ".join(digit_words[digit] for digit in group))

        return ", ".join(spoken_groups)

    def speak_date_of_birth(self, dob):
        try:
            parsed = datetime.strptime(dob, "%m/%d/%Y")
        except ValueError:
            return dob

        months = [
            "",
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]

        return f"{months[parsed.month]} {self.say_ordinal(parsed.day)}, {self.speak_year(parsed.year)}"

    def say_ordinal(self, day):
        ordinals = {
            1: "first",
            2: "second",
            3: "third",
            4: "fourth",
            5: "fifth",
            6: "sixth",
            7: "seventh",
            8: "eighth",
            9: "ninth",
            10: "tenth",
            11: "eleventh",
            12: "twelfth",
            13: "thirteenth",
            14: "fourteenth",
            15: "fifteenth",
            16: "sixteenth",
            17: "seventeenth",
            18: "eighteenth",
            19: "nineteenth",
            20: "twentieth",
            21: "twenty first",
            22: "twenty second",
            23: "twenty third",
            24: "twenty fourth",
            25: "twenty fifth",
            26: "twenty sixth",
            27: "twenty seventh",
            28: "twenty eighth",
            29: "twenty ninth",
            30: "thirtieth",
            31: "thirty first",
        }

        return ordinals.get(day, str(day))

    def speak_year(self, year):
        if 1900 <= year <= 1999:
            return "nineteen " + self.say_number_under_100(year - 1900)

        if 2000 <= year <= 2009:
            if year == 2000:
                return "two thousand"

            return "two thousand " + self.say_number_under_100(year - 2000)

        if 2010 <= year <= 2099:
            return "twenty " + self.say_number_under_100(year - 2000)

        return str(year)

    def say_number_under_100(self, number):
        ones = {
            0: "",
            1: "one",
            2: "two",
            3: "three",
            4: "four",
            5: "five",
            6: "six",
            7: "seven",
            8: "eight",
            9: "nine",
            10: "ten",
            11: "eleven",
            12: "twelve",
            13: "thirteen",
            14: "fourteen",
            15: "fifteen",
            16: "sixteen",
            17: "seventeen",
            18: "eighteen",
            19: "nineteen",
        }

        tens = {
            20: "twenty",
            30: "thirty",
            40: "forty",
            50: "fifty",
            60: "sixty",
            70: "seventy",
            80: "eighty",
            90: "ninety",
        }

        if number < 20:
            return ones[number]

        ten_value = (number // 10) * 10
        one_value = number % 10

        if one_value == 0:
            return tens[ten_value]

        return f"{tens[ten_value]} {ones[one_value]}"

    def understand_agent_message(self, text, profile):
        lower = text.lower()
        agent_phone_digits = self.find_agent_phone_digits(text)
        profile_phone_digits = profile["phone_digits"]

        asks_confirmation = "is that correct" in lower or "confirm" in lower
        has_phone_reference = "phone" in lower or "phone number" in lower

        if has_phone_reference and agent_phone_digits:
            phone_match = "yes" if agent_phone_digits == profile_phone_digits else "no"
        elif has_phone_reference and not agent_phone_digits:
            phone_match = "unknown"
        else:
            phone_match = "not_applicable"

        return "\n".join(
            [
                f"has_phone_reference: {'yes' if has_phone_reference else 'no'}",
                f"agent_phone_digits: {agent_phone_digits or 'none'}",
                f"profile_phone_digits: {profile_phone_digits}",
                f"phone_match: {phone_match}",
                f"asks_confirmation: {'yes' if asks_confirmation else 'no'}",
            ]
        )

    def find_agent_phone_digits(self, text):
        lower = text.lower()

        if "phone" not in lower and "number" not in lower:
            return ""

        segment = lower

        if "phone number" in segment:
            segment = segment.split("phone number", 1)[1]
        elif "phone" in segment:
            segment = segment.split("phone", 1)[1]
        elif "number" in segment:
            segment = segment.split("number", 1)[1]

        stop_words = [
            "date of birth",
            "dob",
            "birthday",
            "birth date",
        ]

        for stop in stop_words:
            index = segment.find(stop)

            if index != -1:
                segment = segment[:index]

        digits = self.keep_digits_only(segment)

        if len(digits) >= 7:
            return digits

        return ""

    def keep_digits_only(self, value):
        return re.sub(r"\D", "", value)

    def make_default_email_from_name(self, name):
        clean_parts = []

        for part in name.split():
            letters_only = "".join(
                character.lower()
                for character in part
                if character.isalpha()
            )

            if letters_only:
                clean_parts.append(letters_only)

        clean = ".".join(clean_parts)

        if not clean:
            clean = "patient"

        return f"{clean}@example.com"

    def _pace_llm_calls(self):
        return self.wait_before_llm_call()

    def _build_profile(self, scenario):
        return self.build_patient_profile(scenario)

    def _dynamic_guardrail_reply(self, scenario, profile, latest_agent_text, transcript):
        return self.handle_basic_rules(
            scenario=scenario,
            profile=profile,
            latest_agent_text=latest_agent_text,
            transcript=transcript,
        )

    def _asks_for_full_name_and_dob(self, lower):
        return self.agent_asks_for_full_name_and_dob(lower)

    def _asks_for_dob(self, lower):
        return self.agent_asks_for_dob(lower)

    def _asks_for_phone(self, lower):
        return self.agent_asks_for_phone(lower)

    def _asks_to_spell_name(self, lower):
        return self.agent_asks_to_spell_name(lower)

    def _asks_how_can_help(self, lower):
        return self.agent_asks_how_can_help(lower)

    def _opening_reply_from_scenario(self, scenario):
        return self.make_opening_reply_from_scenario(scenario)

    def _preferred_time_from_details(self, details):
        return self.find_preferred_time_from_details(details)

    def _extract_offered_time(self, text):
        return self.find_offered_time(text)

    def _sentence_containing(self, text, keywords):
        return self.find_sentence_from_details(text, keywords)

    def _patientize_sentence(self, sentence):
        return self.make_sentence_patient_friendly(sentence)

    def _system_prompt(self):
        return self.make_system_prompt()

    def _case_prompt(self, scenario, profile, transcript, latest_agent_text, turn_count):
        return self.make_case_prompt(
            scenario=scenario,
            profile=profile,
            transcript=transcript,
            latest_agent_text=latest_agent_text,
            turn_count=turn_count,
        )

    def _clean_json(self, raw):
        return self.clean_json_text(raw)

    def _final_cleanup(self, text, profile, latest_agent_text):
        return self.clean_patient_reply(text, profile, latest_agent_text)

    def _spell_name(self, name):
        return self.spell_patient_name(name)

    def _speak_phone(self, phone):
        return self.speak_phone_number(phone)

    def _speak_dob(self, dob):
        return self.speak_date_of_birth(dob)

    def _ordinal(self, day):
        return self.say_ordinal(day)

    def _speak_year(self, year):
        return self.speak_year(year)

    def _speak_number_under_100(self, number):
        return self.say_number_under_100(number)

    def _analyze_latest_agent_message(self, text, profile):
        return self.understand_agent_message(text, profile)

    def _extract_agent_phone_digits(self, text):
        return self.find_agent_phone_digits(text)

    def _digits_only(self, value):
        return self.keep_digits_only(value)

    def _default_email_from_name(self, name):
        return self.make_default_email_from_name(name)