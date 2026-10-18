"""A12 — Kural setinden LaTeX şablonu üretimi.

Yerelde TeX derleyicisi olmadığı için testler yapısaldır: kural değerleri doğru LaTeX ayarına
dönüşüyor mu, dosyalar sözdizimsel olarak dengeli mi, yalnızca TeX Live'daki standart paketler mi
kullanılıyor, kullanıcıya dosya okuyan/yazan komut kalmış mı.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from synora.cli import app
from synora.latex import build_template, build_zip
from synora.ruleset import Ruleset, load_ruleset

ROOT = Path(__file__).resolve().parents[2]
ZBEU = load_ruleset(ROOT / "rulesets" / "zbeu-tip.yaml")
CLS = "synora-zbeu-tip.cls"
runner = CliRunner()

# TeX Live / Overleaf'te standart olarak bulunan paketler. Yenisi bilerek eklenir.
ALLOWED_PACKAGES = {
    "amsmath", "iftex", "fontenc", "newtxtext", "newtxmath", "helvet", "carlito", "fontspec",
    "babel", "etoolbox", "graphicx", "booktabs", "geometry", "setspace", "indentfirst",
    "titlesec", "caption", "footmisc", "fancyhdr", "hyperref",
}


def _zbeu_data() -> dict[str, object]:
    data = yaml.safe_load((ROOT / "rulesets" / "zbeu-tip.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _with(**changes: object) -> Ruleset:
    """ZBEÜ kural setinin üst düzey alanları değiştirilmiş kopyası."""
    data = _zbeu_data()
    data.update(changes)
    return Ruleset.model_validate(data)


def _with_role(role: str, **fields: object) -> Ruleset:
    data = _zbeu_data()
    roles = data["roles"]
    assert isinstance(roles, dict)
    roles[role] = {**roles.get(role, {}), **fields}
    return Ruleset.model_validate(data)


def _strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in tex.splitlines())


def _packages(tex: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(r"\\(?:RequirePackage|usepackage)(?:\[[^\]]*\])?\{([^}]*)\}",
                         _strip_comments(tex)):
        found.update(p.strip() for p in m.group(1).split(","))
    return found


def _cls(rules: Ruleset = ZBEU) -> str:
    t = build_template(rules)
    return t.files[f"{t.class_name}.cls"]


# --- Kural → LaTeX ------------------------------------------------------------------------


def test_zbeu_page_geometry_from_ruleset() -> None:
    assert "\\RequirePackage[a4paper,portrait,top=3cm,bottom=3cm,left=4cm,right=2.5cm]{geometry}" \
        in _cls()


def test_margins_follow_ruleset_changes() -> None:
    rules = _with(page={"size": "B5", "margins_cm": {"top": 2.5, "left": 3.25}})
    cls = _cls(rules)
    assert "\\RequirePackage[b5paper,top=2.5cm,left=3.25cm]{geometry}" in cls


def test_zbeu_body_settings() -> None:
    cls = _cls()
    assert "\\LoadClass[12pt,oneside,openany]{report}" in cls
    assert "\\onehalfspacing" in cls
    assert "\\setlength{\\parindent}{1cm}" in cls
    assert "\\RequirePackage{indentfirst}" in cls
    assert "\\raggedright" not in _strip_comments(cls).split("titlesec")[0]  # gövde iki yana yaslı


def test_times_new_roman_for_both_engines() -> None:
    cls = _cls()
    assert "\\RequirePackage{newtxtext,newtxmath}" in cls
    assert "\\IfFontExistsTF{Times New Roman}{\\setmainfont{Times New Roman}}" \
           "{\\setmainfont{TeX Gyre Termes}}" in cls
    assert cls.index("{amsmath}") < cls.index("newtxmath")


def test_turkish_babel_keeps_equals_sign_inactive() -> None:
    assert "\\RequirePackage[turkish,shorthands=:!]{babel}" in _cls()


def test_zbeu_headings() -> None:
    cls = _cls()
    assert ("\\titleformat{\\chapter}[block]{\\fontsize{14}{16.8}\\selectfont\\bfseries\\centering}"
            "{\\thechapter.}{0.5em}{\\MakeUppercase}") in cls
    assert ("\\titleformat{\\section}{\\fontsize{12}{14.4}\\selectfont\\bfseries\\raggedright}"
            "{\\thesection.}{0.5em}{}") in cls
    assert "\\titleformat{\\subsection}" in cls
    assert "\\titleclass{\\chapter}{straight}" not in cls  # 1. düzey yeni sayfadan


def test_chapter_without_page_break() -> None:
    assert "\\titleclass{\\chapter}{straight}" in _cls(_with_role("heading_1",
                                                                   page_break_before=False))


def test_captions_spacing_and_position() -> None:
    cls = _cls()
    assert "\\captionsetup[figure]{font={onehalfspacing},position=below}" in cls
    assert "\\captionsetup[table]{font={onehalfspacing},position=above}" in cls


def test_caption_size_alignment_and_custom_stretch() -> None:
    cls = _cls(_with_role("table_caption", size_pt=10, alignment="left", line_spacing=1.2,
                          bold=True))
    assert "\\DeclareCaptionFont{synoratable}{\\fontsize{10}{12}\\selectfont}" in cls
    assert ("\\captionsetup[table]{font={synoratable,bf,stretch=1.2},"
            "justification=raggedright,singlelinecheck=false,position=above}") in cls


def test_quote_bibliography_footnote() -> None:
    cls = _cls()
    assert "\\renewenvironment{quote}{\\list{}{\\leftmargin=\\leftmargini\\rightmargin=0pt}" \
           "\\item\\relax\\onehalfspacing}{\\endlist}" in cls
    assert "\\apptocmd{\\thebibliography}{\\onehalfspacing}{}{}" in cls
    assert "\\renewcommand{\\footnotesize}{\\fontsize{10}{12}\\selectfont}" in cls
    assert "footmisc" not in cls  # tek aralık setspace'in varsayılanı


def test_quote_indent_and_footnote_spacing_from_example() -> None:
    cls = _cls(load_ruleset(ROOT / "rulesets" / "example.yaml"))
    assert "\\leftmargin=1cm" in cls
    assert "\\fontsize{11}{13.2}\\selectfont\\singlespacing" in cls
    assert "\\setlength{\\parskip}{6pt}" in cls


def test_page_numbers() -> None:
    cls = _cls()
    assert "\\newcommand{\\onsayfalar}{\\clearpage\\pagenumbering{roman}}" in cls
    assert "\\newcommand{\\anametin}{\\clearpage\\pagenumbering{arabic}}" in cls
    assert "\\fancyfoot[R]{\\thepage}" in cls
    rules = _with(page_numbering={"formats_in_order": ["upperRoman", "decimal"],
                                  "position": "top_center"})
    cls = _cls(rules)
    assert "\\pagenumbering{Roman}" in cls
    assert "\\fancyhead[C]{\\thepage}" in cls


@pytest.mark.parametrize(("size", "line"), [
    (10, "\\LoadClass[10pt,oneside,openany]{report}"),
    (11, "\\LoadClass[11pt,oneside,openany]{report}"),
    (14, "\\LoadClass[14pt,oneside,openany]{extreport}"),
    (13, "\\LoadClass[12pt,oneside,openany]{extreport}"),
])
def test_body_size_selects_base_class(size: int, line: str) -> None:
    assert line in _cls(_with_role("body", size_pt=size))


def test_unknown_font_needs_xelatex() -> None:
    cls = _cls(_with(fonts={"allowed": ["Palatino Linotype"]}))
    assert "\\setmainfont{Palatino Linotype}" in cls
    assert "newtxtext" not in cls


def test_font_name_cannot_inject_tex() -> None:
    evil = "X}\\input{/etc/passwd}"
    t = build_template(_with(fonts={"allowed": [evil]}))
    assert all("passwd" not in text for name, text in t.files.items() if name != "BENIOKU.md")
    assert any(rid == "*.font" for rid, _ in t.manual)


def test_rules_latex_cannot_enforce_are_listed_for_student() -> None:
    t = build_template(ZBEU)
    manual = dict(t.manual)
    assert "heading_2.case" in manual and "heading_3.case" in manual
    assert "table_caption.position" in manual
    readme = t.files["BENIOKU.md"]
    assert "Sizin uymanız gerekenler" in readme
    assert "Resmi bir şablon değildir" in readme
    assert "`page.margin.left` | geometry: left=4cm" in readme


# --- Dosyaların sağlamlığı ----------------------------------------------------------------


def _all_templates() -> list[Ruleset]:
    return [load_ruleset(p) for p in sorted((ROOT / "rulesets").glob("*.yaml"))]


@pytest.mark.parametrize("rules", _all_templates(), ids=lambda r: r.ruleset)
def test_files_are_balanced(rules: Ruleset) -> None:
    for name, text in build_template(rules).files.items():
        if not name.endswith((".tex", ".cls")):
            continue
        body = _strip_comments(text).replace("\\{", "").replace("\\}", "")
        depth = 0
        for ch in body:
            depth += {"{": 1, "}": -1}.get(ch, 0)
            assert depth >= 0, name
        assert depth == 0, name
        begins = re.findall(r"\\begin\{(\w+)\}", body)
        ends = re.findall(r"\\end\{(\w+)\}", body)
        assert sorted(begins) == sorted(ends), name


@pytest.mark.parametrize("rules", _all_templates(), ids=lambda r: r.ruleset)
def test_only_standard_packages(rules: Ruleset) -> None:
    for name, text in build_template(rules).files.items():
        if name.endswith((".tex", ".cls")):
            assert _packages(text) <= ALLOWED_PACKAGES, name


@pytest.mark.parametrize("rules", _all_templates(), ids=lambda r: r.ruleset)
def test_no_file_or_shell_access(rules: Ruleset) -> None:
    for name, text in build_template(rules).files.items():
        code = _strip_comments(text)
        for cmd in ("\\input", "\\include{", "\\write18", "\\openout", "\\openin",
                    "\\immediate", "\\directlua"):
            assert cmd not in code, (name, cmd)


def test_sample_uses_class_commands_and_places_captions() -> None:
    t = build_template(ZBEU)
    tex = t.files["tez.tex"]
    assert "\\documentclass{synora-zbeu-tip}" in tex
    cls = t.files[CLS]
    for cmd in ("onsayfalar", "anametin", "onbolum"):
        assert f"\\newcommand{{\\{cmd}}}" in cls
        assert f"\\{cmd}" in tex
    assert tex.index("\\onsayfalar") < tex.index("\\tableofcontents") < tex.index("\\anametin")
    figure = tex[tex.index("\\begin{figure}"):tex.index("\\end{figure}")]
    assert figure.index("\\fbox") < figure.index("\\caption")  # şekil yazısı altta
    table = tex[tex.index("\\begin{table}"):tex.index("\\end{table}")]
    assert table.index("\\caption") < table.index("\\begin{tabular}")  # tablo başlığı üstte
    assert "\\bibliography{kaynaklar}" in tex
    for key in re.findall(r"\\cite\{([^}]*)\}", tex)[0].split(","):
        assert f"{{{key}," in t.files["kaynaklar.bib"]


def test_zip_is_deterministic_and_flat() -> None:
    data = build_zip(ZBEU)
    assert data == build_zip(ZBEU)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert sorted(names) == sorted(["BENIOKU.md", CLS, "kaynaklar.bib", "tez.tex"])
        assert all("/" not in n and "\\" not in n and not n.startswith(".") for n in names)
        assert zf.read(CLS).decode("utf-8") == _cls()


# --- CLI ----------------------------------------------------------------------------------


def test_cli_writes_directory(tmp_path: Path) -> None:
    out = tmp_path / "sablon"
    res = runner.invoke(app, ["latex", "-r", str(ROOT / "rulesets" / "zbeu-tip.yaml"),
                              "-o", str(out)])
    assert res.exit_code == 0, res.output
    assert (out / CLS).read_text(encoding="utf-8") == _cls()
    assert (out / "tez.tex").exists()


def test_cli_writes_zip_and_refuses_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "sablon.zip"
    args = ["latex", "-r", str(ROOT / "rulesets" / "zbeu-tip.yaml"), "-o", str(out)]
    assert runner.invoke(app, args).exit_code == 0
    assert out.read_bytes() == build_zip(ZBEU)
    out.write_bytes(b"dokunma")
    res = runner.invoke(app, args)
    assert res.exit_code == 2
    assert out.read_bytes() == b"dokunma"
    assert runner.invoke(app, [*args, "--force"]).exit_code == 0
    assert out.read_bytes() == build_zip(ZBEU)


def test_cli_rejects_bad_ruleset(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("ruleset: x\nversion: 0\n", encoding="utf-8")
    res = runner.invoke(app, ["latex", "-r", str(bad), "-o", str(tmp_path / "o")])
    assert res.exit_code == 2
    assert not (tmp_path / "o").exists()
