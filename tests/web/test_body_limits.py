"""Form ve JSON gövdeleri küçük ve beklenen biçimde olmalı: Starlette çok parçalı (multipart)
gövdeyi 1 MB'tan sonra geçici dosyaya yazar; oturumsuz /login ile disk doldurulabilirdi."""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_web import bad_thesis, csrf_from, login, upload, wait_done

from synora.web.mailer import ConsoleMailer


def test_multipart_login_is_refused(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/giris")
    res = client.post("/login", data={"email": "a@beun.edu.tr", "csrf": csrf_from(page.text)},
                      files={"dosya": ("x.bin", b"0" * 2048)})
    assert res.status_code == 415
    assert mailer.sent == []


def test_oversized_form_is_refused(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/giris")
    res = client.post("/login", data={"email": "a@beun.edu.tr", "csrf": csrf_from(page.text),
                                      "dolgu": "x" * 20_000})
    assert res.status_code == 413
    assert mailer.sent == []


def test_oversized_roles_json_is_refused(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    res = client.post(f"/jobs/{job_id}/roles", content=b'{"roles": {}, "x": "' + b"y" * 70_000
                      + b'"}', headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"})
    assert res.status_code == 413


def test_normal_forms_still_work(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)  # /login ve /auth formları
    assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
