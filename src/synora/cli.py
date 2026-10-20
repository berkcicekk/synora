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

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Payper tez biçim denetimi.")


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


@app.callback()
def main() -> None:
    """Payper: tezleri enstitü yazım kılavuzuna göre denetler."""
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


@app.command("fix")
def fix_command(
    docx: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Düzeltilecek .docx")
    ],
    ruleset: Annotated[Path, typer.Option("--ruleset", "-r", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o", help="Düzeltilmiş kopya (.docx)")],
    force: Annotated[bool, typer.Option("--force", help="Var olan dosyanın üzerine yaz")] = False,
) -> None:
    """Düzeltilebilir bulguları izlenen değişiklik olarak uygular; metne dokunmaz.

    Çıktı, write.verify_output kapılarından (metin aynılığı, yapı) geçmeden üretilmez.
    """
    from synora.errors import ErrorCode
    from synora.fix import fix_document

    try:
        rules = load_ruleset(ruleset)
    except (ValidationError, yaml.YAMLError, OSError, ValueError) as exc:
        typer.echo(f"Kural seti okunamadı: {type(exc).__name__}", err=True)
        raise typer.Exit(2) from None
    if output.exists() and not force:
        typer.echo(f"{output} zaten var (--force ile üzerine yazılır).", err=True)
        raise typer.Exit(2)
    limits = Limits()
    if docx.stat().st_size > limits.max_file_bytes:
        typer.echo("Dosya çok büyük. En fazla 50 MB yükleyebilirsiniz.", err=True)
        raise typer.Exit(2)
    try:
        result = fix_document(docx.read_bytes(), rules)
    except SynoraError as exc:
        if exc.code is ErrorCode.NOTHING_TO_FIX:
            typer.echo("Düzeltilebilir bulgu yok; dosya üretilmedi.")
            raise typer.Exit(0) from None
        typer.echo(f"Kopya üretilemedi (kod: {exc.code.value}).", err=True)
        raise typer.Exit(2) from None
    output.write_bytes(result.docx)
    typer.echo(f"{result.fixed} bulgu düzeltildi"
               + (f", {result.skipped} atlandı" if result.skipped else "")
               + f"; yazıldı: {output}")


@app.command("word")
def word_command(
    ruleset: Annotated[Path, typer.Option("--ruleset", "-r", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o", help=".docx dosyası")],
    force: Annotated[bool, typer.Option("--force", help="Var olan dosyanın üzerine yaz")] = False,
) -> None:
    """Kural setinden stilleri hazır Word şablonu (.docx) üretir."""
    from synora.word import build_docx

    try:
        rules = load_ruleset(ruleset)
    except (ValidationError, yaml.YAMLError, OSError, ValueError) as exc:
        typer.echo(f"Kural seti okunamadı: {type(exc).__name__}", err=True)
        raise typer.Exit(2) from None
    if output.exists() and not force:
        typer.echo(f"{output} zaten var (--force ile üzerine yazılır).", err=True)
        raise typer.Exit(2)
    output.write_bytes(build_docx(rules))
    typer.echo(f"Yazıldı: {output}")


@app.command("latex")
def latex_command(
    ruleset: Annotated[Path, typer.Option("--ruleset", "-r", exists=True, dir_okay=False)],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Klasör ya da .zip dosyası")
    ],
    force: Annotated[bool, typer.Option("--force", help="Var olan dosyaların üzerine yaz")] = False,
) -> None:
    """Kural setinden LaTeX tez şablonu üretir (Overleaf'e yüklenebilir)."""
    from synora.latex import build_template, build_zip

    try:
        rules = load_ruleset(ruleset)
    except (ValidationError, yaml.YAMLError, OSError, ValueError) as exc:
        typer.echo(f"Kural seti okunamadı: {type(exc).__name__}", err=True)
        raise typer.Exit(2) from None

    if output.suffix.lower() == ".zip":
        targets = [output]
    else:
        files = build_template(rules).files
        targets = [output / name for name in files]
    existing = [t for t in targets if t.exists()]
    if existing and not force:
        typer.echo(f"Dosya zaten var: {existing[0]} (üzerine yazmak için --force)", err=True)
        raise typer.Exit(2)

    if output.suffix.lower() == ".zip":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(build_zip(rules))
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (output / name).write_text(content, encoding="utf-8", newline="\n")
    typer.echo(f"LaTeX şablonu yazıldı: {output}")


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option(help="Dinlenecek adres")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port")] = 8000,
    dev: Annotated[
        bool, typer.Option("--dev", help="Geliştirme: giriş bağlantısı konsola yazılır")
    ] = False,
) -> None:
    """Web arayüzünü başlatır."""
    import os

    import uvicorn

    if not dev and os.environ.get("SYNORA_DEV") == "1":
        typer.echo("SYNORA_DEV=1 üretimde kullanılamaz; geliştirme için --dev verin.", err=True)
        raise typer.Exit(2)
    if dev:
        os.environ.setdefault("SYNORA_DEV", "1")
        os.environ.setdefault("SYNORA_BASE_URL", f"http://{host}:{port}")
    from synora import log
    from synora.web.app import create_app

    log.configure_logging()
    # Erişim kaydı yalnızca geliştirmede: uvicorn yolu sorgu dizesiyle yazar ve /auth?token=…
    # bağlantısı 15 dakika boyunca giriş demektir; ayrıca istemci IP'si kişisel veridir.
    uvicorn.run(create_app(), host=host, port=port, proxy_headers=True, server_header=False,
                access_log=dev)
