"""A5: düzeltici ve yorumlu kopya. Her çıktı write.verify_output kapılarından geçer;
burada ayrıca sonuçların içeriği ve kapıların gerçekten çalıştığı test edilir."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from builders import p, r
from thesis import BODY_TEXT, MARGINS, front_matter, h1, main_matter, sect, thesis

from synora.annotate import annotate_document
from synora.check import check
from synora.errors import ErrorCode, SynoraError
from synora.fingerprint import content_fingerprint
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.ruleset import load_ruleset
from synora.write import WriteError, repackage, verify_output

ROOT = Path(__file__).resolve().parents[2]
RULES = load_ruleset(ROOT / "rulesets" / "example.yaml")


def findings(data: bytes) -> list[tuple[str, str, str]]:
    result = check(parse_package(open_docx(data)), RULES)
    return [(f.rule_id, f.expected, f.actual) for f in result.findings]


def doc_xml(data: bytes) -> str:
    return zipfile.ZipFile(__import__("io").BytesIO(data)).read("word/document.xml").decode()


BAD_PARAGRAPHS = {
    "line_spacing": p(BODY_TEXT, ppr='<w:spacing w:line="240" w:lineRule="auto"/>'),
    "exact_line": p(BODY_TEXT, ppr='<w:spacing w:line="240" w:lineRule="exact"/>'),
    "alignment": p(BODY_TEXT, ppr='<w:jc w:val="left"/>'),
    "first_line": p(BODY_TEXT, ppr='<w:ind w:firstLine="0"/>'),
    "space_after": p(BODY_TEXT, ppr='<w:spacing w:after="0"/>'),
    "size": p(r(BODY_TEXT, rpr='<w:sz w:val="22"/>')),
    "font": p(r(BODY_TEXT, rpr='<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>')),
    "mixed_runs": p(r("Kısmen "), r("yanlış", rpr='<w:rFonts w:ascii="Calibri"/>'), r(" yazı.")),
    "many": p(r(BODY_TEXT, rpr='<w:sz w:val="22"/><w:rFonts w:ascii="Arial"/>'),
              ppr='<w:jc w:val="left"/><w:spacing w:line="240"/><w:ind w:firstLine="0"/>'),
}


@pytest.mark.parametrize("name", sorted(BAD_PARAGRAPHS))
def test_body_fixes_are_resolved(name: str) -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS[name]))
    before = findings(data)
    assert before, name
    fixed = fix_document(data, RULES)
    assert fixed.fixed == len(before)
    assert findings(fixed.docx) == [
        ("document.tracked_changes", "false", "true")
    ]
    assert content_fingerprint(open_docx(fixed.docx)) == content_fingerprint(open_docx(data))


def test_changes_are_tracked_as_synora() -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["many"]))
    xml = doc_xml(fix_document(data, RULES).docx)
    assert xml.count("<w:pPrChange") == 1  # paragraf başına tek kayıt
    assert xml.count("<w:rPrChange") == 1
    assert 'w:author="Synora"' in xml
    # Eski değerler kayıtta saklanır: öğrenci reddederse geri döner.
    change = xml[xml.index("<w:pPrChange"):]
    assert 'w:line="240"' in change.split("</w:pPrChange>")[0]


def test_ppr_child_order_follows_schema() -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["many"]))
    xml = doc_xml(fix_document(data, RULES).docx)
    ppr = xml[xml.rindex("<w:pPr>", 0, xml.index("<w:pPrChange")):xml.index("<w:pPrChange")]
    assert ppr.index("<w:spacing") < ppr.index("<w:ind") < ppr.index("<w:jc")


def test_page_and_margin_fixes() -> None:
    letter = '<w:pgSz w:w="12240" w:h="15840"/>'
    margins = '<w:pgMar w:top="1440"/>'
    body = front_matter() + main_matter().replace(sect("decimal"),
                                                  sect("decimal", page=letter, margins=margins))
    data = thesis(body)
    assert {f[0] for f in findings(data)} == {"page.size", "page.margin.top", "page.margin.bottom",
                                             "page.margin.left", "page.margin.right"}
    fixed = fix_document(data, RULES)
    assert [f[0] for f in findings(fixed.docx)] == ["document.tracked_changes"]
    xml = doc_xml(fixed.docx)
    assert xml.count("<w:sectPrChange") == 1
    # pgMar şemada tüm öznitelikleri zorunlu tutar
    current = xml[:xml.rindex("<w:sectPrChange")]  # değişiklik kaydından önceki yeni değerler
    pg_mar = current[current.rindex("<w:pgMar"):].split("/>")[0]
    for attr in ("top", "bottom", "left", "right", "header", "footer", "gutter"):
        assert f'w:{attr}="' in pg_mar


def test_missing_final_section_is_created() -> None:
    data = thesis(front_matter() + main_matter().replace(sect("decimal"), ""))
    fixed = fix_document(data, RULES)
    remaining = {f[0] for f in findings(fixed.docx)}
    assert "page.size" not in remaining
    assert "page.margin.top" not in remaining


def test_page_numbering_fixed_when_groups_match() -> None:
    body = h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("upperRoman")) + main_matter()
    fixed = fix_document(thesis(body), RULES)
    assert "page_numbering.formats" not in {f[0] for f in findings(fixed.docx)}


def test_page_numbering_not_guessed_when_groups_differ() -> None:
    body = h1("ÖNSÖZ") + p(BODY_TEXT, ppr=sect("decimal")) + main_matter()
    data = thesis(body)
    result = check(parse_package(open_docx(data)), RULES)
    numbering = next(f for f in result.findings if f.rule_id == "page_numbering.formats")
    assert not numbering.fixable


def test_heading_bold_and_page_break() -> None:
    heading = p("YÖNTEM", ppr='<w:pStyle w:val="Heading1"/><w:pageBreakBefore w:val="0"/>')
    heading = heading.replace("<w:r>", '<w:r><w:rPr><w:b w:val="0"/></w:rPr>', 1)
    fixed = fix_document(thesis(front_matter() + main_matter(extra=heading)), RULES)
    assert [f[0] for f in findings(fixed.docx)] == ["document.tracked_changes"]


def test_italic_removal_is_never_automatic() -> None:
    from synora.ruleset import Ruleset
    rules = Ruleset.model_validate({**RULES.model_dump(mode="json"),
                                    "roles": {"body": {"italic": False}}})
    data = thesis(front_matter() + main_matter(extra=p(r(BODY_TEXT, rpr="<w:i/>"))))
    result = check(parse_package(open_docx(data)), rules)
    italic = [f for f in result.findings if f.rule_id == "body.italic"]
    assert italic and not italic[0].fixable


def test_students_own_tracked_change_is_left_alone() -> None:
    own = p(BODY_TEXT, ppr='<w:spacing w:line="240"/><w:pPrChange w:id="900" w:author="Öğrenci">'
                           '<w:pPr><w:jc w:val="left"/></w:pPr></w:pPrChange>')
    data = thesis(front_matter() + main_matter(extra=own + BAD_PARAGRAPHS["alignment"]))
    fixed = fix_document(data, RULES)
    assert fixed.skipped == 1
    assert ("body.line_spacing", "1.5", "1.0") in findings(fixed.docx)


def test_nothing_to_fix() -> None:
    with pytest.raises(SynoraError) as exc:
        fix_document(thesis(), RULES)
    assert exc.value.code is ErrorCode.NOTHING_TO_FIX


def test_revision_ids_are_unique() -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["many"] * 3))
    xml = doc_xml(fix_document(data, RULES).docx)
    import re
    ids = re.findall(r'<w:(?:pPrChange|rPrChange|sectPrChange) w:id="(\d+)"', xml)
    assert len(ids) == len(set(ids)) > 3


# --- Kapılar gerçekten çalışıyor mu? ------------------------------------------------------


def test_gate_catches_text_change() -> None:
    data = thesis()
    pkg = open_docx(data)
    tampered = repackage(pkg, {"word/document.xml": pkg.parts["word/document.xml"].replace(
        "ÖNSÖZ".encode(), "ÖNSÖZ!".encode())})
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, tampered, modified_parts={"word/document.xml"},
                      expected_structure_delta=Counter(), check_findings=lambda _: set(),
                      before_findings=set(), must_disappear=set(), allowed_new=set())
    assert exc.value.code is ErrorCode.WRITE_TEXT_CHANGED


def test_gate_catches_added_empty_paragraph() -> None:
    data = thesis()
    pkg = open_docx(data)
    xml = pkg.parts["word/document.xml"].replace(b"<w:body>", b"<w:body><w:p/>", 1)
    tampered = repackage(pkg, {"word/document.xml": xml})
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, tampered, modified_parts={"word/document.xml"},
                      expected_structure_delta=Counter(), check_findings=lambda _: set(),
                      before_findings=set(), must_disappear=set(), allowed_new=set())
    assert exc.value.code is ErrorCode.WRITE_TEXT_CHANGED


def test_gate_catches_untouched_part_change() -> None:
    data = thesis()
    pkg = open_docx(data)
    styles = pkg.parts["word/styles.xml"].replace(b'w:val="24"', b'w:val="26"', 1)
    tampered = repackage(pkg, {"word/styles.xml": styles})
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, tampered, modified_parts=set(),
                      expected_structure_delta=Counter(), check_findings=lambda _: set(),
                      before_findings=set(), must_disappear=set(), allowed_new=set())
    assert exc.value.code is ErrorCode.WRITE_UNEXPECTED_CHANGE


def test_gate_catches_new_findings() -> None:
    data = thesis()
    pkg = open_docx(data)
    with pytest.raises(WriteError) as exc:
        verify_output(pkg, data, modified_parts=set(), expected_structure_delta=Counter(),
                      check_findings=lambda _: {("body.size_pt", "p1", None)},
                      before_findings=set(), must_disappear=set(), allowed_new=set())
    assert exc.value.code is ErrorCode.WRITE_NEW_FINDINGS


# --- Yorumlu kopya ---------------------------------------------------------------------------


def test_annotated_copy() -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["many"]))
    out = annotate_document(data, RULES)
    z = zipfile.ZipFile(__import__("io").BytesIO(out))
    comments = z.read("word/comments.xml").decode()
    assert comments.count("<w:comment ") == 1
    assert "Satır aralığı 1,0. Kılavuz 1,5 istiyor." in comments
    assert "Yazı tipi Arial." in comments
    assert "comments.xml" in z.read("word/_rels/document.xml.rels").decode()
    assert "comments+xml" in z.read("[Content_Types].xml").decode()
    assert content_fingerprint(open_docx(out)) == content_fingerprint(open_docx(data))
    assert findings(out) == findings(data)  # yorumlar biçimi değiştirmez


def test_annotation_keeps_existing_comments() -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["alignment"]))
    first = annotate_document(data, RULES)
    second = annotate_document(first, RULES)  # öğrencinin (burada önceki) yorumları korunur
    comments = zipfile.ZipFile(__import__("io").BytesIO(second)).read("word/comments.xml")
    assert comments.decode().count("<w:comment ") == 2


# --- LibreOffice ile açılabilirlik ------------------------------------------------------------

SOFFICE = shutil.which("soffice") or (
    r"C:\Program Files\LibreOffice\program\soffice.exe"
    if Path(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() else None
)


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice kurulu değil")
@pytest.mark.parametrize("kind", ["fixed", "annotated"])
def test_libreoffice_opens_output(tmp_path: Path, kind: str) -> None:
    data = thesis(front_matter() + main_matter(extra=BAD_PARAGRAPHS["many"]).replace(
        MARGINS, '<w:pgMar w:top="1440"/>'))
    out = (fix_document(data, RULES).docx if kind == "fixed" else annotate_document(data, RULES))
    src = tmp_path / f"{kind}.docx"
    src.write_bytes(out)
    profile = (tmp_path / "lo-profile").as_uri()
    subprocess.run(
        [str(SOFFICE), f"-env:UserInstallation={profile}", "--headless", "--norestore",
         "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
        check=True, timeout=180, capture_output=True,
    )
    pdf = tmp_path / f"{kind}.pdf"
    assert pdf.exists() and pdf.stat().st_size > 1000


# --- Kullanıcının seçtiği roller -------------------------------------------------------------

AMBIGUOUS = p(r("Araştırmanın sınırlılıkları", rpr="<w:b/>"))


def _ambiguous_thesis() -> tuple[bytes, dict[str, Role]]:
    data = thesis(front_matter() + main_matter(extra=AMBIGUOUS))
    result = check(parse_package(open_docx(data)), RULES)
    pid = next(k for k, d in result.roles.items() if d.role is Role.UNKNOWN)
    return data, {pid: Role.HEADING_2}


def test_fix_uses_user_roles() -> None:
    data, roles = _ambiguous_thesis()
    with pytest.raises(SynoraError):  # rol seçilmeden düzeltilecek bir şey yok
        fix_document(data, RULES)
    fixed = fix_document(data, RULES, user_roles=roles)
    assert fixed.fixed >= 1
    after = check(parse_package(open_docx(fixed.docx)), RULES, user_roles=roles)
    assert [f.rule_id for f in after.findings if f.fixable] == []
    assert content_fingerprint(open_docx(fixed.docx)) == content_fingerprint(open_docx(data))


def test_annotation_uses_user_roles() -> None:
    data, roles = _ambiguous_thesis()
    out = annotate_document(data, RULES, user_roles=roles)
    comments = zipfile.ZipFile(__import__("io").BytesIO(out)).read("word/comments.xml").decode()
    assert "2. düzey başlık" in comments
