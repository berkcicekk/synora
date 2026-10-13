"""A9–A11 uçtan uca: giriş, yükleme, rapor, yetki, güvenlik başlıkları, saklama süresi."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from builders import p, r
from fastapi.testclient import TestClient
from thesis import front_matter, main_matter, thesis

from synora.web.app import create_app
from synora.web.mailer import ConsoleMailer
from synora.web.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
SECRET = "Bu cümle tezin gizli gövde metnidir"


@pytest.fixture
def mailer() -> ConsoleMailer:
    return ConsoleMailer(echo=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "t.db", rulesets_dir=ROOT / "rulesets", base_url="http://testserver",
        allowed_domains=("beun.edu.tr",), dev=True, isolate_jobs=False, workers=1,
    )


@pytest.fixture
def client(settings: Settings, mailer: ConsoleMailer) -> Iterator[TestClient]:
    with TestClient(create_app(settings, mailer)) as c:
        yield c


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html) or re.search(r'data-csrf="([^"]+)"', html)
    assert m, html[:500]
    return m.group(1)


def login(client: TestClient, mailer: ConsoleMailer, email: str = "ogrenci@beun.edu.tr") -> str:
    page = client.get("/")
    res = client.post("/login", data={"email": email, "csrf": csrf_from(page.text)})
    assert res.status_code == 200, res.text
    link = mailer.sent[-1][1]
    token = link.split("token=")[1]
    confirm = client.get(f"/auth?token={token}")
    res = client.post("/auth", data={"token": token, "csrf": csrf_from(confirm.text)},
                      follow_redirects=False)
    assert res.status_code == 303
    home = client.get("/")
    assert "Tezinizi yükleyin" in home.text
    return csrf_from(home.text.split('id="upload"')[1])


def upload(client: TestClient, csrf: str, data: bytes, ruleset: str = "example") -> str:
    res = client.post("/jobs", content=data, headers={
        "X-CSRF-Token": csrf, "X-Ruleset": ruleset, "Content-Type": "application/octet-stream"})
    assert res.status_code == 202, res.text
    return str(res.json()["id"])


def wait_done(client: TestClient, job_id: str) -> str:
    for _ in range(1200):  # yük altında (ör. LibreOffice testleri) 60 sn'ye kadar bekle
        status = client.get(f"/jobs/{job_id}/status").json()["status"]
        if status not in ("queued", "running"):
            return str(status)
        time.sleep(0.05)
    raise AssertionError("iş bitmedi")


def bad_thesis() -> bytes:
    bad = p(r(SECRET), ppr='<w:spacing w:line="240"/>')
    return thesis(front_matter() + main_matter(extra=bad))


# --- Giriş -------------------------------------------------------------------------------


def test_login_flow_and_upload_report(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    assert wait_done(client, job_id) == "done"
    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert "1 hata, 0 uyarı." in page.text
    assert "Satır aralığı 1,0. Kılavuz 1,5 istiyor." in page.text
    assert "GİRİŞ › 1.1 Amaç" in page.text  # başlık yolu
    assert SECRET not in page.text
    report = client.get(f"/jobs/{job_id}/report.json")
    assert report.status_code == 200
    assert SECRET not in report.text
    assert report.headers["content-disposition"].startswith("attachment")


def test_domain_not_allowed(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/")
    res = client.post("/login", data={"email": "biri@gmail.com", "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert "üniversite e-posta" in res.text
    assert mailer.sent == []


def test_login_requires_csrf(client: TestClient, mailer: ConsoleMailer) -> None:
    client.get("/")
    res = client.post("/login", data={"email": "ogrenci@beun.edu.tr", "csrf": "yanlis"})
    assert res.status_code == 403
    assert mailer.sent == []


def test_link_preview_does_not_consume_token(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/")
    client.post("/login", data={"email": "a@beun.edu.tr", "csrf": csrf_from(page.text)})
    token = mailer.sent[-1][1].split("token=")[1]
    for _ in range(3):  # e-posta tarayıcıları bağlantıyı önceden açabilir
        assert "Giriş yap" in client.get(f"/auth?token={token}").text


def test_token_single_use(client: TestClient, mailer: ConsoleMailer) -> None:
    page = client.get("/")
    client.post("/login", data={"email": "a@beun.edu.tr", "csrf": csrf_from(page.text)})
    token = mailer.sent[-1][1].split("token=")[1]
    csrf = csrf_from(client.get(f"/auth?token={token}").text)
    client.post("/auth", data={"token": token, "csrf": csrf}, follow_redirects=False)
    again = client.get(f"/auth?token={token}")
    assert again.status_code == 400
    assert "süresi dolmuş" in again.text


def test_login_rate_limit(client: TestClient, mailer: ConsoleMailer, settings: Settings) -> None:
    for _ in range(settings.login_requests_per_hour + 1):
        page = client.get("/")
        res = client.post("/login", data={"email": "a@beun.edu.tr", "csrf": csrf_from(page.text)})
    assert res.status_code == 400
    assert "Çok fazla" in res.text
    assert len(mailer.sent) == settings.login_requests_per_hour


# --- Yükleme ve yetki ---------------------------------------------------------------------


def test_upload_requires_login(client: TestClient) -> None:
    res = client.post("/jobs", content=b"x", headers={"X-CSRF-Token": "x", "X-Ruleset": "example"},
                      follow_redirects=False)
    assert res.status_code in (303, 401)


def test_upload_requires_csrf(client: TestClient, mailer: ConsoleMailer) -> None:
    login(client, mailer)
    res = client.post("/jobs", content=thesis(), headers={"X-CSRF-Token": "yanlis",
                                                          "X-Ruleset": "example"})
    assert res.status_code == 403


def test_upload_too_large(client: TestClient, mailer: ConsoleMailer, settings: Settings) -> None:
    csrf = login(client, mailer)
    big = b"0" * (settings.max_upload_bytes + 1)
    res = client.post("/jobs", content=big, headers={"X-CSRF-Token": csrf, "X-Ruleset": "example"})
    assert res.status_code == 413


def test_unknown_ruleset(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    res = client.post("/jobs", content=thesis(), headers={"X-CSRF-Token": csrf,
                                                          "X-Ruleset": "../../etc/passwd"})
    assert res.status_code == 400


def test_rejected_file_shows_message(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, b"bu bir word belgesi degil")
    assert wait_done(client, job_id) == "failed"
    page = client.get(f"/jobs/{job_id}")
    assert "Bu dosya bir Word belgesi (.docx) değil." in page.text
    assert "NOT_A_ZIP" in page.text


def test_other_users_job_is_404(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        job_id = upload(alice, login(alice, mailer, "alice@beun.edu.tr"), thesis())
        wait_done(alice, job_id)
        login(bob, mailer, "bob@beun.edu.tr")
        assert bob.get(f"/jobs/{job_id}").status_code == 404
        assert bob.get(f"/jobs/{job_id}/report.json").status_code == 404
        assert bob.get(f"/jobs/{job_id}/status").status_code == 404


def test_concurrent_job_limit(
    client: TestClient, mailer: ConsoleMailer, settings: Settings
) -> None:
    csrf = login(client, mailer)
    db = client.app.state.db  # type: ignore[attr-defined]
    for i in range(settings.max_active_jobs):
        db.add_job(f"bekleyen-is-{i:08d}", "ogrenci@beun.edu.tr", "example")
    res = client.post("/jobs", content=thesis(), headers={"X-CSRF-Token": csrf,
                                                          "X-Ruleset": "example"})
    assert res.status_code == 429


def test_user_can_delete_report(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, thesis())
    wait_done(client, job_id)
    res = client.post(f"/jobs/{job_id}/delete", data={"csrf": csrf}, follow_redirects=False)
    assert res.status_code == 303
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_logout(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    client.post("/logout", data={"csrf": csrf})
    assert "Giriş bağlantısı gönder" in client.get("/").text


# --- Güvenlik ve saklama ------------------------------------------------------------------


def test_security_headers(client: TestClient) -> None:
    res = client.get("/")
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["cache-control"] == "no-store"


def test_no_inline_scripts_or_styles(client: TestClient, mailer: ConsoleMailer) -> None:
    pages = [client.get("/").text]
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    pages += [client.get("/").text, client.get(f"/jobs/{job_id}").text]
    for html in pages:
        assert "<script>" not in html
        assert "style=" not in html
        assert "<style" not in html


def test_no_external_resources(client: TestClient) -> None:
    html = client.get("/").text
    assert "googleapis" not in html
    assert not re.search(r'(src|href)="https?://', html)


def test_retention_purge(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, thesis())
    wait_done(client, job_id)
    db = client.app.state.db  # type: ignore[attr-defined]
    db.execute("UPDATE jobs SET created_at = created_at - 90000 WHERE id=?", (job_id,))
    assert db.purge(24 * 3600) == 1
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_thesis_bytes_never_written_to_db(client: TestClient, mailer: ConsoleMailer,
                                         settings: Settings) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    raw = settings.db_path.read_bytes()
    for wal in settings.db_path.parent.glob("*.db-wal"):
        raw += wal.read_bytes()
    assert SECRET.encode() not in raw
    assert b"PK\x03\x04" not in raw  # zip başlığı yok


def test_static_fonts_served_locally(client: TestClient) -> None:
    css = client.get("/static/fonts.css")
    assert css.status_code == 200
    assert "fonts.gstatic.com" not in css.text
    assert client.get("/static/fonts/latin-modern-roman-regular.woff2").status_code == 200


# --- F5: düzeltilmiş / yorumlu kopya ---------------------------------------------------------


def output(client: TestClient, csrf: str, job_id: str, kind: str, data: bytes):  # type: ignore[no-untyped-def]
    return client.post(f"/jobs/{job_id}/output/{kind}", content=data,
                       headers={"X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})


@pytest.mark.parametrize("kind", ["fixed", "annotated"])
def test_output_with_same_file(client: TestClient, mailer: ConsoleMailer, kind: str) -> None:
    from synora.fingerprint import content_fingerprint
    from synora.ingest import open_docx

    csrf = login(client, mailer)
    data = bad_thesis()
    job_id = upload(client, csrf, data)
    assert wait_done(client, job_id) == "done"
    assert "Düzeltilmiş kopyayı indir" in client.get(f"/jobs/{job_id}").text
    res = output(client, csrf, job_id, kind, data)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in res.headers["content-disposition"]
    assert content_fingerprint(open_docx(res.content)) == content_fingerprint(open_docx(data))


def test_output_rejects_different_file(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    job_id = upload(client, csrf, bad_thesis())
    wait_done(client, job_id)
    res = output(client, csrf, job_id, "fixed", thesis())
    assert res.status_code == 409
    assert "denetlenen dosya değil" in res.json()["error"]


def test_output_requires_csrf_and_ownership(settings: Settings, mailer: ConsoleMailer) -> None:
    app = create_app(settings, mailer)
    with TestClient(app) as alice, TestClient(app) as bob:
        data = bad_thesis()
        a_csrf = login(alice, mailer, "alice@beun.edu.tr")
        job_id = upload(alice, a_csrf, data)
        wait_done(alice, job_id)
        assert output(alice, "yanlis", job_id, "fixed", data).status_code == 403
        b_csrf = login(bob, mailer, "bob@beun.edu.tr")
        assert output(bob, b_csrf, job_id, "fixed", data).status_code == 404


def test_output_nothing_to_fix(client: TestClient, mailer: ConsoleMailer) -> None:
    csrf = login(client, mailer)
    data = thesis()
    job_id = upload(client, csrf, data)
    wait_done(client, job_id)
    res = output(client, csrf, job_id, "fixed", data)
    assert res.status_code == 422
    assert "NOTHING_TO_FIX" in res.json()["error"]


def test_source_hash_stored_not_file(client: TestClient, mailer: ConsoleMailer,
                                     settings: Settings) -> None:
    import hashlib
    csrf = login(client, mailer)
    data = bad_thesis()
    job_id = upload(client, csrf, data)
    wait_done(client, job_id)
    job = client.app.state.db.get_job(job_id)  # type: ignore[attr-defined]
    assert job.source_sha256 == hashlib.sha256(data).hexdigest()


def test_css_respects_hidden_attribute(client: TestClient) -> None:
    # .button/.card display tanımları [hidden]'ı ezerse onay düğmesi ve filtreler bozulur.
    css = client.get("/static/app.css").text
    assert "[hidden] { display: none !important; }" in css


def test_pricing_page_is_public(client: TestClient, mailer: ConsoleMailer) -> None:
    res = client.get("/fiyatlandirma")
    assert res.status_code == 200
    assert "Fiyatlandırma" in res.text
    assert "Test aşamasında" in res.text
    assert 'aria-current="page"' in res.text
    login(client, mailer)
    assert client.get("/fiyatlandirma").status_code == 200


def test_report_view_counts_grouped_findings() -> None:
    from synora.web.app import report_view

    def finding(block: int) -> dict[str, object]:
        return {"rule_id": "body.line_spacing", "expected": "1.5", "actual": "1.0",
                "message": "m", "severity": "error", "fixable": True, "block": block}

    view = report_view({"summary": {}, "ruleset": {}, "findings": [finding(0), finding(3)]})
    assert len(view["cards"]) == 1
    assert view["finding_count"] == 2
    assert view["cards"][0]["count"] == 2
