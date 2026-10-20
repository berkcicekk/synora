import json
from pathlib import Path

import pytest
import yaml
from builders import p, r
from pydantic import ValidationError
from thesis import front_matter, main_matter, thesis
from typer.testing import CliRunner

from synora.check import Finding, Severity, check
from synora.cli import app
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.report import message, to_json, to_text
from synora.ruleset import Ruleset, load_ruleset

EXAMPLE = Path(__file__).resolve().parents[2] / "rulesets" / "example.yaml"
RULES = load_ruleset(EXAMPLE)
SECRET = "Bu cümle tezin gizli içeriğidir"
runner = CliRunner()


def bad_thesis() -> bytes:
    bad = p(r(SECRET, rpr='<w:rFonts w:ascii="Arial"/>'), ppr='<w:spacing w:line="240"/>')
    return thesis(front_matter() + main_matter(extra=bad * 3))


# --- Mesajlar -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("finding", "expected"),
    [
        (Finding("body.line_spacing", Severity.ERROR, "1.5", "1.0", True),
         "Satır aralığı 1,0. Kılavuz 1,5 istiyor."),
        (Finding("body.line_spacing", Severity.ERROR, "1.5", "exact:12pt", True),
         "Satır aralığı tam 12 pt. Kılavuz 1,5 istiyor."),
        (Finding("page.margin.left", Severity.ERROR, "3.5cm", "2.54cm", True),
         "Sol kenar boşluğu 2,54 cm. Kılavuz 3,5 cm istiyor."),
        (Finding("body.alignment", Severity.ERROR, "justify", "left", True),
         "Hizalama sola yaslı. Kılavuz iki yana yaslı istiyor."),
        (Finding("heading_1.bold", Severity.ERROR, "true", "false", True),
         "Metin kalın değil. Kılavuz kalın olmasını istiyor."),
        (Finding("page_numbering.formats", Severity.ERROR, "lowerRoman,decimal", "decimal", True),
         "Sayfa numaralandırma sırası: 1, 2, 3. Kılavuz: i, ii, iii; sonra 1, 2, 3."),
    ],
)
def test_messages(finding: Finding, expected: str) -> None:
    assert message(finding) == expected


# --- Raporlar metin sızdırmaz ---------------------------------------------------------------


def test_reports_group_and_never_contain_text() -> None:
    result = check(parse_package(open_docx(bad_thesis())), RULES)
    text = to_text(result, RULES)
    js = to_json(result, RULES)
    assert SECRET not in text
    assert SECRET not in js
    assert "6 hata, 0 uyarı" in text
    assert "3 paragraf: ¶" in text
    data = json.loads(js)
    assert data["summary"]["errors"] == 6
    assert {f["rule_id"] for f in data["findings"]} == {"body.font", "body.line_spacing"}
    assert all(f["role"] == Role.BODY.value for f in data["findings"])


def test_clean_report() -> None:
    result = check(parse_package(open_docx(thesis())), RULES)
    assert "Kılavuza aykırı biçim bulunamadı." in to_text(result, RULES)


# --- Kural seti şeması ----------------------------------------------------------------------


def test_example_ruleset_loads() -> None:
    assert RULES.ruleset == "example"
    assert RULES.roles[Role.BODY].spacing_rule() is not None


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Ruleset.model_validate({"ruleset": "x", "version": 1, "name": "X", "sayfa": {}})


def test_unknown_role_rejected() -> None:
    with pytest.raises(ValidationError):
        Ruleset.model_validate({"ruleset": "x", "version": 1, "name": "X",
                                "roles": {"baslik": {"size_pt": 12}}})


def test_line_spacing_needs_exactly_one_kind() -> None:
    with pytest.raises(ValidationError):
        Ruleset.model_validate({"ruleset": "x", "version": 1, "name": "X",
                                "roles": {"body": {"line_spacing": {"multiple": 1.5,
                                                                    "exact_pt": 12}}}})


def test_yaml_is_safe_loaded(tmp_path: Path) -> None:
    evil = tmp_path / "evil.yaml"
    evil.write_text("ruleset: !!python/object/apply:os.system ['echo x']\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_ruleset(evil)


# --- CLI ------------------------------------------------------------------------------------


def write(tmp_path: Path, data: bytes, name: str = "tez.docx") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_cli_clean_exit_0(tmp_path: Path) -> None:
    res = runner.invoke(app, ["check", str(write(tmp_path, thesis())), "-r", str(EXAMPLE)])
    assert res.exit_code == 0, res.output
    assert "bulunamadı" in res.output


def test_cli_findings_exit_1_json(tmp_path: Path) -> None:
    res = runner.invoke(app, ["check", str(write(tmp_path, bad_thesis())), "-r", str(EXAMPLE),
                              "--format", "json"])
    assert res.exit_code == 1
    assert json.loads(res.output)["summary"]["errors"] == 6
    assert SECRET not in res.output


def test_cli_output_file(tmp_path: Path) -> None:
    out = tmp_path / "rapor.json"
    res = runner.invoke(app, ["check", str(write(tmp_path, bad_thesis())), "-r", str(EXAMPLE),
                              "-f", "json", "-o", str(out)])
    assert res.exit_code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["errors"] == 6


def test_cli_rejected_file_exit_2(tmp_path: Path) -> None:
    res = runner.invoke(app, ["check", str(write(tmp_path, b"zip degil")), "-r", str(EXAMPLE)])
    assert res.exit_code == 2
    assert "NOT_A_ZIP" in res.output


def test_cli_bad_ruleset_exit_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("ruleset: x\nversion: 0\nname: X\n", encoding="utf-8")
    res = runner.invoke(app, ["check", str(write(tmp_path, thesis())), "-r", str(bad)])
    assert res.exit_code == 2


@pytest.mark.parametrize(
    "content", ["ruleset: [kapanmamis\n", "!!python/object/apply:os.system ['x']\n"]
)
def test_cli_malformed_yaml_exit_2(tmp_path: Path, content: str) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(content, encoding="utf-8")
    res = runner.invoke(app, ["check", str(write(tmp_path, thesis())), "-r", str(bad)])
    assert res.exit_code == 2
    assert res.exception is None or isinstance(res.exception, SystemExit)


# --- Denetlenen maddeler (Ö2): bulgu çıkmayan kurallar da raporda görünür ------------------------


def test_report_lists_checked_and_compliant_rules() -> None:
    result = check(parse_package(open_docx(thesis())), RULES)
    doc = json.loads(to_json(result, RULES))
    ids = [c["rule_id"] for c in doc["checked_rules"]]
    assert "body.line_spacing" in ids
    assert "page.margin.left" in ids
    assert "heading_1.page_break_before" in ids
    assert all(c["label"] for c in doc["checked_rules"])


def test_rule_with_finding_is_not_listed_as_compliant() -> None:
    bad = p("Satır aralığı bozuk paragraf.", ppr='<w:spacing w:line="240" w:lineRule="auto"/>')
    data = thesis(front_matter() + main_matter(extra=bad))
    result = check(parse_package(open_docx(data)), RULES)
    doc = json.loads(to_json(result, RULES))
    assert "body.line_spacing" in {f["rule_id"] for f in doc["findings"]}
    assert "body.line_spacing" not in {c["rule_id"] for c in doc["checked_rules"]}


def test_text_report_mentions_compliant_count() -> None:
    bad = p("Satır aralığı bozuk paragraf.", ppr='<w:spacing w:line="240" w:lineRule="auto"/>')
    data = thesis(front_matter() + main_matter(extra=bad))
    result = check(parse_package(open_docx(data)), RULES)
    assert "madde daha denetlendi ve uygun bulundu" in to_text(result, RULES)


def test_ruleset_warning_reaches_report() -> None:
    # Kılavuz-şablon çelişkisi olan kural setleri uyarı taşır; rapor bunu gösterir.
    warned = load_ruleset(Path(EXAMPLE).parent / "btu-lee.yaml")
    assert warned.uyari
    result = check(parse_package(open_docx(thesis())), warned)
    doc = json.loads(to_json(result, warned))
    assert doc["ruleset"]["uyari"] == warned.uyari
    assert f"UYARI: {warned.uyari}" in to_text(result, warned)


# --- synora fix (A8): mimarinin vadettiği CLI düzeltme komutu ------------------------------------


def test_cli_fix_writes_corrected_copy(tmp_path: Path) -> None:
    from synora.fingerprint import content_fingerprint
    from synora.ingest import open_docx

    bad = p("Satır aralığı bozuk paragraf.", ppr='<w:spacing w:line="240" w:lineRule="auto"/>')
    src = tmp_path / "tez.docx"
    src.write_bytes(thesis(front_matter() + main_matter(extra=bad)))
    out = tmp_path / "tez-duzeltilmis.docx"
    result = runner.invoke(app, ["fix", str(src), "-r", str(EXAMPLE), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "düzeltildi" in result.output
    fixed = out.read_bytes()
    assert content_fingerprint(open_docx(fixed)) == content_fingerprint(open_docx(src.read_bytes()))
    check_again = runner.invoke(app, ["check", str(out), "-r", str(EXAMPLE), "-f", "json"])
    report = json.loads(check_again.output)
    assert "body.line_spacing" not in {f["rule_id"] for f in report["findings"]}


def test_cli_fix_nothing_to_fix(tmp_path: Path) -> None:
    src = tmp_path / "tez.docx"
    src.write_bytes(thesis())
    out = tmp_path / "out.docx"
    result = runner.invoke(app, ["fix", str(src), "-r", str(EXAMPLE), "-o", str(out)])
    assert result.exit_code == 0
    assert not out.exists()  # düzeltilecek bir şey yoksa dosya üretilmez
