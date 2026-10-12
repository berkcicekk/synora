"""Rol sınıflandırma doğruluğu: etiketli sentetik derlem üzerinde ölçülür.

Hedefler (docs/plan.md, F3):
- Kesinlik: sınıflandırıcının rol verdiği (UNKNOWN olmayan) paragraflarda ≥ %90 doğru.
- Kapsam: rolü bilinen paragrafların ≥ %85'ine rol verilmeli.
- Yanlış denetim: "belirsiz kalmalı" etiketli satırlara denetlenen bir rol verilmemeli.
"""

from collections import Counter

import pytest
from builders import make_docx
from corpus import STYLES, build

from synora.check import SKIPPED_ROLES
from synora.ingest import open_docx
from synora.model import Role
from synora.parse import parse_package
from synora.roles import assign_roles

SEEDS = range(12)


def evaluate(seed: int) -> list[tuple[Role, Role]]:
    samples = build(seed)
    doc = parse_package(open_docx(make_docx("".join(x for x, _ in samples), styles=STYLES)))
    roles = assign_roles(doc)
    body = doc.body()
    # Tablo örneği iki hücre paragrafı üretir: etiketleri belge sırasına aç.
    expected: list[Role] = []
    for xml, role in samples:
        expected.extend([role] * max(xml.count("<w:p>") + xml.count("<w:p "), 1))
    assert len(expected) == len(body), (seed, len(expected), len(body))
    return [(want, roles[p.para_id].role) for want, p in zip(expected, body, strict=True)]


@pytest.fixture(scope="module")
def pairs() -> list[tuple[Role, Role]]:
    out: list[tuple[Role, Role]] = []
    for seed in SEEDS:
        out.extend(evaluate(seed))
    return out


def test_precision(pairs: list[tuple[Role, Role]]) -> None:
    decided = [(w, g) for w, g in pairs if g is not Role.UNKNOWN and w is not Role.UNKNOWN]
    correct = sum(w == g for w, g in decided)
    errors = Counter((w.value, g.value) for w, g in decided if w != g)
    precision = correct / len(decided)
    print(f"\nkesinlik={precision:.3f} ({correct}/{len(decided)}) hatalar={dict(errors)}")
    assert precision >= 0.90, errors


def test_coverage(pairs: list[tuple[Role, Role]]) -> None:
    known = [(w, g) for w, g in pairs if w is not Role.UNKNOWN]
    covered = sum(g is not Role.UNKNOWN for _, g in known)
    missed = Counter(w.value for w, g in known if g is Role.UNKNOWN)
    coverage = covered / len(known)
    print(f"\nkapsam={coverage:.3f} ({covered}/{len(known)}) belirsiz kalan={dict(missed)}")
    assert coverage >= 0.85, missed


def test_ambiguous_lines_are_never_checked(pairs: list[tuple[Role, Role]]) -> None:
    wrongly_checked = Counter(
        g.value for w, g in pairs if w is Role.UNKNOWN and g not in SKIPPED_ROLES
    )
    assert wrongly_checked == Counter()


def test_body_sentences_mentioning_figures_are_body(pairs: list[tuple[Role, Role]]) -> None:
    # Derlemdeki gövde cümleleri "Şekil 3.1'de..." gibi atıflar içerir; başlık sanılmamalı.
    body_errors = Counter(g.value for w, g in pairs if w is Role.BODY and g is not Role.BODY)
    assert body_errors == Counter()


def _roles_of(*paragraphs: str) -> list[Role]:
    doc = parse_package(open_docx(make_docx("".join(paragraphs), styles=STYLES)))
    roles = assign_roles(doc)
    return [roles[p.para_id].role for p in doc.body()]


LONG = (
    "Bu çalışmanın amacı öğretmenlerin ölçme ve değerlendirme süreçlerine ilişkin "
    "görüşlerini ayrıntılı biçimde incelemek ve uygulamaya dönük öneriler geliştirmektir."
)


def test_holdout_no_cover_page_first_body_is_checked() -> None:
    from builders import p
    assert _roles_of(p(LONG), p(LONG)) == [Role.BODY, Role.BODY]


def test_holdout_dedication_is_not_body() -> None:
    from builders import p, r
    brk = p('<w:r><w:br w:type="page"/></w:r>')
    dedication = p(r("Aileme", rpr="<w:i/>"), ppr='<w:jc w:val="right"/>')
    assert _roles_of(p(LONG), brk, dedication)[-1] is Role.UNKNOWN


def test_holdout_short_justified_sentence_is_body() -> None:
    from builders import p
    roles = _roles_of(p(LONG), p("Bu bölümde yöntem açıklanmıştır."))
    assert roles[-1] is Role.BODY


def test_holdout_bold_sentence_with_period_is_body() -> None:
    from builders import p, r
    roles = _roles_of(p(LONG), p(r("Bu sonuç araştırmanın en önemli bulgusudur.", rpr="<w:b/>")))
    assert roles[-1] is Role.BODY
