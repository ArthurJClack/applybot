import json

from applybot.answers import AnswerBank, Field, choose_option, classify, resolve_fields
from conftest import FakeLLM


def test_classify():
    assert classify("First Name *") == "first_name"
    assert classify("Last name") == "last_name"
    assert classify("Email address") == "email"
    assert classify("Phone number") == "phone"
    assert classify("Will you now or in the future require visa sponsorship?") == \
        "work_authorization.requires_sponsorship"
    assert classify("Are you legally authorized to work in the United States?") == \
        "work_authorization.authorized_to_work"
    assert classify("Gender") == "eeo.gender"
    assert classify("Are you Hispanic/Latino?") == "eeo.hispanic_latino"
    assert classify("Resume/CV") == "resume_file"
    assert classify("LinkedIn Profile") == "linkedin"
    assert classify("Are you willing to relocate?") == "logistics.willing_to_relocate"
    assert classify("Expected graduation date") == "graduation"
    assert classify("Have you ever been convicted of a felony?") == "sensitive.criminal_conviction"
    assert classify("Excellent communicator?") is None  # no false 'cell' phone match
    assert classify("Why do you want to work here?") is None


def test_choose_option():
    opts = ["Select...", "Yes", "No"]
    assert choose_option("Yes", opts) == "Yes"
    assert choose_option("no", opts) == "No"
    eeo = ["Male", "Female", "Non-binary", "I don't wish to answer"]
    assert choose_option("Decline to self-identify", eeo) == "I don't wish to answer"
    vet = ["I am a protected veteran", "I am not a protected veteran", "I prefer not to answer"]
    assert choose_option("I am not a protected veteran", vet) == "I am not a protected veteran"
    auth = ["Yes, I am authorized", "No, I am not authorized"]
    assert choose_option("Yes", auth) == "Yes, I am authorized"
    assert choose_option("No", auth) == "No, I am not authorized"
    assert choose_option("Computer Science", ["Biology", "Computer Science & Engineering"]) == \
        "Computer Science & Engineering"


def test_resolve_never_sends_sensitive_to_ai(tmp_path, profile, job):
    (tmp_path / "a.yaml").write_text("work_authorization:\n  requires_sponsorship: 'No'\nsensitive:\n  criminal_conviction: ''\ncustom:\n  favorite color: Blue\n")
    bank = AnswerBank(tmp_path / "a.yaml", profile, cover_letter_text="Dear team...")
    fields = [
        Field("f1", "text", "First Name", True),
        Field("f2", "email", "Email", True),
        Field("f3", "select", "Gender", False, ["Male", "Female", "Decline to self-identify"]),
        Field("f4", "radio", "Will you require sponsorship?", True, ["Yes", "No"]),
        Field("f5", "textarea", "Why do you want to join Widgets Inc?", True),
        Field("f6", "radio", "Have you been convicted of a crime?", True, ["Yes", "No"]),
        Field("f7", "text", "What's your favorite color?", False),
        Field("f8", "textarea", "Cover Letter", False),
        Field("f9", "text", "School", True),
    ]

    def handler(prompt):
        payload = json.loads(prompt.split("FIELDS:")[1])
        return {"answers": {f["key"]: "Because I love building APIs." for f in payload}}
    llm = FakeLLM(handler)
    asked = []
    res = resolve_fields(fields, bank, profile, job, llm, ask_human=lambda f: asked.append(f.question) or "No")
    assert res["f1"].value == "Alex" and res["f1"].source == "rule"
    assert res["f2"].value == "alex.rivera@example.com"
    assert res["f3"].value == "Decline to self-identify"
    assert res["f4"].value == "No"
    assert res["f5"].source == "ai"
    assert res["f6"].source == "human" and asked == ["Have you been convicted of a crime?"]
    assert res["f7"].value == "Blue" and res["f7"].source == "saved"
    assert res["f8"].value == "Dear team..."
    assert res["f9"].value == "University of Texas at Austin"
    sent = llm.prompts[0]
    assert "convicted" not in sent and "Gender" not in sent and "sponsorship" not in sent
    # human answer was learned and persisted
    assert AnswerBank(tmp_path / "a.yaml", profile).saved_answer("Have you been convicted of a crime?") == "No"


def test_open_ended_questions_skip_short_value_rules(tmp_path, profile):
    bank = AnswerBank(tmp_path / "a.yaml", profile)
    for q, kind in [("Describe a major project you are proud of", "textarea"),
                    ("Tell us about working on a hybrid team", "textarea"),
                    ("Describe a major project you are proud of", "text")]:
        assert bank.rule_answer(Field("x", kind, q, True))[0] is None, q
    assert classify("Are you currently employed?") is None
    assert classify("Major") == "major"


def test_legal_answers_are_not_prefilled(tmp_path, profile):
    bank = AnswerBank(tmp_path / "missing.yaml", profile)
    for q in ("Will you require sponsorship?", "Are you legally authorized to work in the US?",
              "Are you at least 18 years old?"):
        assert bank.rule_answer(Field("x", "radio", q, True, ["Yes", "No"]))[0] is None, q
