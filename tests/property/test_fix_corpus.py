"""A5 stres testi: derlemdeki farklı "öğrenci alışkanlıkları" ile üretilmiş tezler.

Her biri düzeltilir ve yorumlanır; beş doğrulama kapısının hiçbiri patlamamalı.
"""

import pytest
from builders import make_docx
from corpus import STYLES, build
from thesis import sect

from synora.annotate import annotate_document
from synora.check import check
from synora.errors import ErrorCode, SynoraError
from synora.fix import fix_document
from synora.ingest import open_docx
from synora.parse import parse_package
from synora.ruleset import load_ruleset

RULES = load_ruleset("rulesets/example.yaml")


def corpus_doc(seed: int) -> bytes:
    body = "".join(x for x, _ in build(seed)) + sect("decimal", margins='<w:pgMar w:top="1440"/>')
    return make_docx(body, styles=STYLES)


@pytest.mark.parametrize("seed", range(12))
def test_fix_and_annotate_corpus(seed: int) -> None:
    data = corpus_doc(seed)
    before = check(parse_package(open_docx(data)), RULES)
    fixable = [f for f in before.findings if f.fixable]
    assert fixable
    try:
        fixed = fix_document(data, RULES)
    except SynoraError as exc:  # kapılardan biri patladıysa testi başarısız say
        pytest.fail(f"düzeltme başarısız: {exc.code}")
    assert fixed.fixed + fixed.skipped == len(fixable)
    after = check(parse_package(open_docx(fixed.docx)), RULES)
    assert sum(f.fixable for f in after.findings) <= fixed.skipped
    try:
        annotate_document(data, RULES)
    except SynoraError as exc:
        assert exc.code is ErrorCode.NOTHING_TO_FIX
