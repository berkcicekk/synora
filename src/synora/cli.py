"""A8 — Komut satırı: `synora check tez.docx --ruleset rulesets/example.yaml`.

Çıkış kodları: 0 hata yok · 1 kılavuza aykırı biçim var · 2 dosya ya da kural seti kabul edilmedi.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from synora.check import Severity, check
from synora.errors import SynoraError
from synora.ingest import Limits, open_docx
from synora.parse import parse_package
from synora.report import ingest_message, to_json, to_text
from synora.ruleset import load_ruleset

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Synora tez biçim denetimi.")


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


@app.callback()
def main() -> None:
    """Synora: tezleri enstitü yazım kılavuzuna göre denetler."""
    # Windows konsolu (cp1254) bazı karakterleri yazamaz: çökmek yerine yer tutucu bas.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


@app.command("check")
def check_command(
    docx: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Denetlenecek .docx")
    ],
    ruleset: Annotated[Path, typer.Option("--ruleset", "-r", exists=True, dir_okay=False)],
    output_format: Annotated[OutputFormat, typer.Option("--format", "-f")] = OutputFormat.TEXT,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Raporu dosyaya yaz")
    ] = None,
) -> None:
    """Bir tezi kural setine göre denetler."""
    try:
        rules = load_ruleset(ruleset)
    except (ValidationError, yaml.YAMLError, OSError, ValueError) as exc:
        typer.echo(f"Kural seti okunamadı: {type(exc).__name__}", err=True)
        raise typer.Exit(2) from None

    limits = Limits()
    if docx.stat().st_size > limits.max_file_bytes:
        typer.echo("Dosya çok büyük. En fazla 50 MB yükleyebilirsiniz.", err=True)
        raise typer.Exit(2)
    try:
        doc = parse_package(open_docx(docx.read_bytes(), limits))
    except SynoraError as exc:
        typer.echo(f"{ingest_message(exc.code)} (kod: {exc.code.value})", err=True)
        raise typer.Exit(2) from None

    result = check(doc, rules)
    text = to_json(result, rules) if output_format is OutputFormat.JSON else to_text(result, rules)
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        typer.echo(text, nl=False)
    has_errors = any(f.severity is Severity.ERROR for f in result.findings)
    raise typer.Exit(1 if has_errors else 0)
