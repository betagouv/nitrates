from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", ["/.well-known/security.txt", "/security.txt"])
def test_security_txt(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert res["Content-Type"] == "text/plain; charset=utf-8"

    body = res.content.decode("utf-8")
    lines = dict(line.split(": ", 1) for line in body.splitlines() if line)
    assert lines["Contact"] == "mailto:nitrates@beta.gouv.fr"
    assert lines["Preferred-Languages"] == "fr, en"
    assert lines["Canonical"].endswith("/.well-known/security.txt")

    # Expires : date valide, dans le futur, et sous le max RFC (1 an)
    expires = datetime.fromisoformat(lines["Expires"])
    now = datetime.now(timezone.utc)
    assert now < expires <= now + timedelta(days=366)


@pytest.mark.parametrize("path", ["/.well-known/security.txt", "/security.txt"])
def test_security_txt_reste_public_en_lockdown(client, settings, path):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    res = client.get(path)
    assert res.status_code == 200
