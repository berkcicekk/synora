"""Kural seti dosyalarını doğrular: şema, kimlik = dosya adı, kaynak alanları, LaTeX üretimi.

Kullanım: python -m uv run python tools/validate_rulesets.py rulesets/a.yaml rulesets/b.yaml ...
(argüman verilmezse rulesets/*.yaml)
"""

from __future__ import annotations

import sys
from pathlib import Path

from synora.latex import build_template
from synora.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[1]


def validate(path: Path) -> list[str]:
    try:
        rules = load_ruleset(path)
    except Exception as exc:  # doğrulama aracı: her hatayı raporla
        return [f"şema: {exc}"]
    problems: list[str] = []
    if rules.ruleset != path.stem:
        problems.append(f"ruleset kimliği ({rules.ruleset}) dosya adıyla ({path.stem}) aynı olmalı")
    if path.stem not in ("example",):
        for name in ("institution", "source", "source_url"):
            if not getattr(rules, name):
                problems.append(f"{name} alanı eksik")
    if not rules.roles and rules.page.margins_cm is None:
        problems.append("ne kenar boşluğu ne rol kuralı var: kural seti boş")
    try:
        build_template(rules)
    except Exception as exc:
        problems.append(f"LaTeX şablonu üretilemedi: {exc}")
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted((ROOT / "rulesets").glob("*.yaml"))
    failed = 0
    for path in paths:
        problems = validate(path)
        if problems:
            failed += 1
            print(f"HATA {path.name}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"tamam {path.name}")
    print(f"{len(paths) - failed}/{len(paths)} geçerli")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
