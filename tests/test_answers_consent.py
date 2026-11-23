from applybot.answers import AnswerBank, Field, resolve_fields


def test_learned_consent_is_never_replayed(tmp_path):
    bank = AnswerBank(tmp_path / "answers.yaml", {"contact": {"name": "A"}})
    q = "Snowflake will process your personal information in accordance with the Snowflake Candidate Privacy Notice."
    bank.learn(q, "I have read and agree to the Snowflake Candidate Privacy Notice.")
    bank.learn("In any materials you submit, you may redact or remove age-identifying information", "I Acknowledge")
    fields = [Field("f1", "checkbox_group", q, True, ["I have read and agree"]),
              Field("f2", "checkbox_group", "In any materials you submit, you may redact or remove age-identifying information",
                    True, ["I Acknowledge"])]
    out = resolve_fields(fields, bank, {}, {}, None)
    assert out["f1"].value is None and out["f2"].value is None


def test_save_keeps_answers_added_to_the_file_meanwhile(tmp_path):
    import yaml
    p = tmp_path / "answers.yaml"
    bank = AnswerBank(p, {"contact": {"name": "A"}})
    bank.save()
    d = yaml.safe_load(p.read_text()); d.setdefault("custom", {})["are you a collector"] = "No"
    p.write_text(yaml.safe_dump(d))
    bank.learn("Favorite color?", "Blue")          # stale in-memory copy saves
    d = yaml.safe_load(p.read_text())
    assert d["custom"]["are you a collector"] == "No" and d["learned"]["Favorite color?"] == "Blue"
