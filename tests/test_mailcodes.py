from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

from applybot.mailcodes import MailCodes, code_from_message, extract_code

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)


def mail(subject, body, sender="no-reply@us.greenhouse-mail.io", when=NOW, html=False):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = sender, subject, format_datetime(when)
    m.set_content(body, subtype="html" if html else "plain")
    return m


def test_extract_code():
    assert extract_code("Your security code is: aB3dE9xY") == "aB3dE9xY"
    assert extract_code("Copy and paste this code into the security code field:\n\n  Qw7RtZ2p\n\nThanks") == "Qw7RtZ2p"
    assert extract_code("Verification code: 482913") == "482913"
    assert extract_code("Use the code below to continue.\nkTmWqLrZ\n") == "kTmWqLrZ"
    assert extract_code("Thanks for applying. The code of conduct applies to everyone.") is None
    assert extract_code("") is None


def test_code_from_message_filters_old_and_unrelated():
    since = NOW - timedelta(minutes=1)
    assert code_from_message(mail("Security code for your application", "Your security code is: aB3dE9xY"), since) == "aB3dE9xY"
    assert code_from_message(mail("Security code", "code is: aB3dE9xY", when=NOW - timedelta(hours=2)), since) is None
    assert code_from_message(mail("Lunch?", "door code: 4821", sender="friend@example.com"), since) is None
    assert code_from_message(mail("Verify", "<p>Your verification code is <b>771204</b></p>", html=True), since) == "771204"


def test_mailcodes_not_ready_without_credentials():
    assert not MailCodes({"mail": {"enabled": True}}).ready
    assert not MailCodes({"mail": {"user": "a@b.c", "app_password": "x"}}).ready
    m = MailCodes({"mail": {"enabled": True, "user": "a@b.c", "app_password": "ab cd"}})
    assert m.ready and m.password == "abcd"


def test_latest_code_picks_first_match(monkeypatch):
    m = MailCodes({"mail": {"enabled": True, "user": "a@b.c", "app_password": "x"}})
    msgs = [mail("Newsletter", "hello", sender="news@example.com"), mail("Security code", "Your security code is: Zz9Yy8Xx")]
    monkeypatch.setattr(m, "_recent", lambda since, limit=15: msgs)
    assert m.latest_code(NOW - timedelta(minutes=5)) == "Zz9Yy8Xx"
