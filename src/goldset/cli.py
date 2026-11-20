"""goldset run <sources> <prompts>: build a golden dataset."""

import asyncio
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import typer

from .config import load_config
from .runner import run as run_build

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)  # never print API keys in tracebacks


def _load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@app.command()
def run(
    sources: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of source files (text, or .json with a glossary .md)."),
    prompts: Path = typer.Argument(..., exists=True, help="A prompt file, or a folder of .md/.txt prompts."),
    out: Path | None = typer.Option(None, help="Run folder. Default runs/<date>_<sources folder name>. Re-use it to resume."),
    config: Path = typer.Option(Path("goldset.yaml"), help="Settings file (optional)."),
) -> None:
    """Plan, generate, verify and self-correct until every case is accepted, dropped or sent to a human."""
    _load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise typer.BadParameter("OPENAI_API_KEY is not set (put it in .env or the environment)")
    out = out or Path("runs") / f"{date.today().isoformat()}_{sources.resolve().name}"
    asyncio.run(run_build(sources, prompts, out, load_config(config), log=typer.echo))
    typer.echo(f"report: {out / 'report.md'}")


@app.command()
def report(run_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Print a finished run's report."""
    typer.echo((run_dir / "report.md").read_text())


@app.command()
def ui(port: int = typer.Option(8501)) -> None:
    """Open the web UI: upload JSON records, their description and prompts."""
    script = Path(__file__).with_name("ui.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(script), "--server.port", str(port),
                    "--server.address", "127.0.0.1", "--server.headless", "true", "--browser.gatherUsageStats", "false"], check=False)


def main() -> None:
    app()
