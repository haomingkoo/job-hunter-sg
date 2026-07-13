import pytest


class _FakeSMTP:
    def __init__(self, host, port, timeout=30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def _clear_email_env(monkeypatch):
    for name in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
        "SMTP_FROM",
        "SMTP_REPLY_TO",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
        "SMTP_FROM_NAME",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_send_email_uses_gmail_smtp_env(monkeypatch):
    import email_service

    _clear_email_env(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "jobs@kooexperience.com")
    monkeypatch.setenv("SMTP_PASS", "app-password")
    monkeypatch.setenv("SMTP_FROM", "Job Hunter SG <jobs@kooexperience.com>")
    monkeypatch.setenv("SMTP_REPLY_TO", "jobs@kooexperience.com")
    instances = []

    def fake_smtp(host, port, timeout=30):
        instance = _FakeSMTP(host, port, timeout)
        instances.append(instance)
        return instance

    monkeypatch.setattr(email_service.smtplib, "SMTP", fake_smtp)

    email_service.send_email(
        "user@example.com",
        "New jobs",
        "Plain text",
        "<p>HTML</p>",
        list_unsubscribe_url="https://job.example.com/unsub",
    )

    assert email_service.email_configured() is True
    assert email_service.email_provider() == "smtp"
    assert instances[0].host == "smtp.gmail.com"
    assert instances[0].port == 587
    assert instances[0].started_tls is True
    assert instances[0].login_args == ("jobs@kooexperience.com", "app-password")
    assert instances[0].message["From"] == "Job Hunter SG <jobs@kooexperience.com>"
    assert instances[0].message["Reply-To"] == "jobs@kooexperience.com"
    assert instances[0].message["List-Unsubscribe"] == "<https://job.example.com/unsub>"
    assert instances[0].message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_send_email_raises_when_no_provider_configured(monkeypatch):
    import email_service

    _clear_email_env(monkeypatch)

    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        email_service.send_email("user@example.com", "Subject", "Text", "<p>HTML</p>")
