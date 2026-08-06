"""Developer/debug CLI for hypr-vocal-command."""

import json

import httpx
import typer

from . import handlers
from .appscan import discover_apps, write_generated_apps
from .config import generated_apps_path, load_config
from .executor import execute
from .llm.client import OllamaClient
from .llm.prompts import build_system_prompt
from .registry import validate_startup

validate_startup(handlers.EXPECTED_INTENTS)

app = typer.Typer(add_completion=False)


@app.callback()
def _main() -> None:
    """hypr-vocal-command developer/debug CLI."""


@app.command("debug-execute")
def debug_execute(payload: str) -> None:
    """Execute a hand-written JSON intent envelope directly (bypasses the LLM entirely)."""
    raw = json.loads(payload)
    result = execute(raw)
    typer.echo(f"ok={result.ok} message={result.message}")
    raise typer.Exit(code=0 if result.ok else 1)


@app.command("scan-apps")
def scan_apps(
    write: bool = typer.Option(False, "--write", help="Persist results to apps.generated.toml"),
) -> None:
    """Scan installed .desktop files and print (or persist) discovered app/package aliases."""
    entries = discover_apps()

    if not entries:
        typer.echo("No applications discovered.")
        raise typer.Exit(code=0)

    for entry in entries:
        pkg = entry.package_name or ("(flatpak)" if entry.manager == "flatpak" else "-")
        typer.echo(
            f"{entry.key:45} {entry.manager:8} {entry.identifier:35} "
            f"pkg={pkg:20} forms=[{', '.join(entry.surface_forms)}]"
        )

    typer.echo(f"\n{len(entries)} applications discovered.")

    if write:
        path = generated_apps_path()
        write_generated_apps(entries, path)
        typer.echo(f"Wrote {path}")


@app.command("classify")
def classify(text: str) -> None:
    """Classify text into a raw intent envelope via the LLM, without executing anything."""
    config = load_config()
    with OllamaClient(
        model=config.model_en, base_url=config.ollama_base_url, timeout=config.llm_timeout_s
    ) as client:
        try:
            result = client.classify(build_system_prompt(), text)
        except httpx.HTTPError as exc:
            typer.echo(f"LLM request failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(f"latency_ms={result.latency_ms:.0f}")
    typer.echo(f"raw={result.raw_response}")


@app.command("check-golden")
def check_golden(
    fixture: str = typer.Option(
        "tests/fixtures/golden_phrases_en.json",
        "--fixture",
        help="Path to a golden-phrase JSON fixture",
    ),
    lang: str = typer.Option(
        "en",
        "--lang",
        help="Language whose model/system-prompt to validate against (en or ar)",
    ),
) -> None:
    """Classify every phrase in a golden-phrase fixture via the real LLM and report
    pass/fail + latency for each.

    Not part of the fast pytest suite -- this hits the real running Ollama model, the
    same way every ad-hoc regression check this project has relied on so far did. Run
    this after any prompt/schema change instead of retyping a phrase list from memory.
    `--lang` matters since English and Arabic now use separate system prompts (each
    with only its own language's few-shot examples) -- pass the language matching the
    fixture, e.g. `--fixture tests/fixtures/golden_phrases_ar.json --lang ar`.
    """
    from pathlib import Path

    config = load_config()
    cases = json.loads(Path(fixture).read_text())

    arg_keys = ("app_name", "workspace", "action", "package_name", "scope")
    correct = 0
    known = 0
    latencies: list[float] = []
    with OllamaClient(
        model=config.model_for(lang), base_url=config.ollama_base_url, timeout=config.llm_timeout_s
    ) as client:
        for case in cases:
            try:
                result = client.classify(build_system_prompt(lang), case["text"])
            except httpx.HTTPError as exc:
                typer.echo(f"LLM request failed: {exc}", err=True)
                raise typer.Exit(code=1) from exc

            got_args = result.envelope.get("args", {})
            got_intent = result.envelope.get("intent")
            ok = got_intent == case["intent"]
            mismatched_args = [
                key for key in arg_keys if key in case and got_args.get(key) != case[key]
            ]
            # HYPRLAND_ACTION's `action` is free text that only means something once
            # resolved, and several distinct actions share wording ("close this tab" vs
            # "close this window" -- one closes a browser tab, the other kills the whole
            # focused window). Asserting the literal string would be brittle since any
            # registered synonym is equally valid, so a fixture can instead declare the
            # `dispatcher` it must resolve to, which is what actually gets executed.
            if "dispatcher" in case:
                alias = config.resolve_hyprland_action(got_args.get("action", ""))
                if alias is None or alias.dispatcher != case["dispatcher"]:
                    got = alias.dispatcher if alias else "<unresolvable>"
                    mismatched_args.append(f"dispatcher={got}")
            ok = ok and not mismatched_args
            correct += ok
            latencies.append(result.latency_ms)

            # A case can be marked as a known, accepted limitation of the LLM path. It
            # still runs and is still reported loudly, so the signal is never hidden --
            # it just doesn't wedge the exit code at 1 forever, which would make this
            # command useless as a pass/fail gate for everything else. Mark a case this
            # way only when the wrong answer is genuinely covered elsewhere (e.g. the
            # fastpath resolves it deterministically) and further prompt tuning has been
            # tried and made things worse.
            limitation = case.get("known_limitation")
            if ok:
                flag = "OK  "
            elif limitation:
                flag = "KNOWN"
                known += 1
            else:
                flag = "FAIL"
            detail = f" MISMATCHED={mismatched_args}" if mismatched_args else ""
            if limitation and not ok:
                detail += f"  [known: {limitation}]"
            typer.echo(
                f"[{flag}] {result.latency_ms:6.0f}ms {case['text']!r:45} -> "
                f"{got_intent} (want {case['intent']}) args={got_args}{detail}"
            )

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    summary = f"\n{correct}/{len(cases)} correct, avg latency {avg_latency:.0f}ms"
    if known:
        summary += f" ({known} known limitation(s), not counted as failures)"
    typer.echo(summary)
    raise typer.Exit(code=0 if correct + known == len(cases) else 1)


@app.command("review-log")
def review_log(
    hours: float = typer.Option(
        24.0,
        "--hours",
        help="Only include commands from the last N hours (0 = everything ever logged)",
    ),
    path: str = typer.Option(
        None,
        "--path",
        help="Path to events.jsonl (default: the real state dir this daemon logs to)",
    ),
) -> None:
    """Review real voice commands from the telemetry log: what was said, what the
    pipeline decided, and what happened -- meant to be run after a day of real use.

    Lists every command, not just failures: a wrong action can still log ok=true (this
    project has hit that twice for real), so filtering to failures would hide exactly
    the mistakes worth catching. Use this to spot misclassifications, then fix them
    (a config.py alias, a llm/prompts.py example) and add the phrase to the matching
    golden-phrase fixture so `check-golden` catches it again automatically next time.
    """
    import time
    from pathlib import Path

    from .review import review as build_review
    from .utils.telemetry import events_path

    config = load_config()
    since = time.time() - hours * 3600 if hours > 0 else None
    log_path = Path(path) if path else events_path()

    typer.echo(build_review(path=log_path, since=since, confidence_threshold=config.confidence_threshold))


@app.command("run-text")
def run_text(text: str) -> None:
    """Classify text via the LLM and execute the resulting intent (full pipeline, no audio)."""
    config = load_config()
    with OllamaClient(
        model=config.model_en, base_url=config.ollama_base_url, timeout=config.llm_timeout_s
    ) as client:
        try:
            result = client.classify(build_system_prompt(), text)
        except httpx.HTTPError as exc:
            typer.echo(f"LLM request failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    exec_result = execute(
        result.envelope,
        config,
        raw_llm_response=result.raw_response,
        llm_latency_ms=result.latency_ms,
    )
    typer.echo(f"latency_ms={result.latency_ms:.0f} ok={exec_result.ok} message={exec_result.message}")
    raise typer.Exit(code=0 if exec_result.ok else 1)


@app.command("record-once")
def record_once(
    model_path: str = typer.Option(
        None, "--model-path", help="Path to a specific ggml model file (default: tiny)"
    ),
) -> None:
    """Record a single VAD-gated utterance from the mic and print the transcript.

    No LLM classification or execution -- just audio capture -> VAD -> whisper.cpp.
    Requires the optional `audio` extra (`pip install -e '.[audio]'`).
    """
    from pathlib import Path

    from .audio import capture
    from .audio.transcribe import load_model, transcribe
    from .audio.vad import SileroVAD, UtteranceConfig, record_utterance
    from .audio.vocabulary import build_command_vocabulary_prompt

    config = load_config()

    typer.echo("Listening... (speak now; a pause after speech ends the recording)")
    vad = SileroVAD()
    audio = record_utterance(vad, UtteranceConfig())

    if audio is None:
        typer.echo("No speech detected.")
        raise typer.Exit(code=1)

    typer.echo(f"Recorded {len(audio) / capture.SAMPLE_RATE:.1f}s, transcribing...")
    model = load_model(model_path=Path(model_path) if model_path else None)
    result = transcribe(
        model,
        audio,
        initial_prompt=build_command_vocabulary_prompt(config),
        allowed_languages=config.allowed_transcription_languages,
    )

    typer.echo(f"transcript={result.text!r}")
    typer.echo(f"language={result.language} probability={result.language_probability:.2f}")
    typer.echo(
        f"(unrestricted top pick: {result.raw_top_language} "
        f"p={result.raw_top_probability:.2f})"
    )


@app.command("run-once")
def run_once(
    lang: str = typer.Option("en", "--lang", help="Language pipeline to use (en or ar)"),
) -> None:
    """Full manual pipeline: record -> transcribe -> classify -> execute.

    Cold: builds a fresh whisper model / VAD / classifier for this one run, unlike the
    daemon which keeps all three warm. Same `pipeline.run_pipeline()` either way --
    requires the optional `audio` extra (`pip install -e '.[audio]'`).
    """
    from .audio import wav2vec2_ctc
    from .audio.transcribe import load_model
    from .audio.vad import SileroVAD
    from .audio.vocabulary import build_command_vocabulary_prompt
    from .daemon import SUPPORTED_LANGUAGES
    from .llm.cache import CachedClassifier
    from .pipeline import run_pipeline

    if lang not in SUPPORTED_LANGUAGES:
        typer.echo(
            f"Unsupported --lang {lang!r}; supported: {', '.join(SUPPORTED_LANGUAGES)}.", err=True
        )
        raise typer.Exit(code=1)

    config = load_config()

    typer.echo("Listening... (speak now; a pause after speech ends the recording)")
    vad = SileroVAD()
    model = load_model()
    with CachedClassifier(
        OllamaClient(
            model=config.model_for(lang),
            base_url=config.ollama_base_url,
            timeout=config.llm_timeout_s,
        )
    ) as classifier:
        try:
            result = run_pipeline(
                vad=vad,
                whisper_model=model,
                classifier=classifier,
                system_prompt=build_system_prompt(lang),
                vocabulary_prompt=build_command_vocabulary_prompt(config, lang),
                config=config,
                language=lang,
                arabic_transcriber=(
                    wav2vec2_ctc.load_transcriber() if wav2vec2_ctc.is_available() else None
                ),
            )
        except httpx.HTTPError as exc:
            typer.echo(f"LLM request failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(f"transcript={result.transcript!r}")
    typer.echo(
        f"transcribe_ms={result.transcribe_ms:.0f} llm_latency_ms={result.llm_latency_ms:.0f} "
        f"total_ms={result.total_ms:.0f}  ok={result.ok} message={result.message}"
    )
    raise typer.Exit(code=0 if result.ok else 1)


@app.command("daemon")
def daemon_cmd() -> None:
    """Run the warm daemon in the foreground (for testing; Phase 8 wires this into
    a systemd --user unit + real hotkey). Ctrl+C to stop.

    Requires the optional `audio` extra (`pip install -e '.[audio]'`).
    """
    import asyncio

    from .daemon import run_daemon

    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        typer.echo("\nStopped.")


@app.command("mic-check")
def mic_check(
    duration: float = typer.Option(5.0, "--duration", help="Seconds to record"),
) -> None:
    """Record for a few seconds and report peak/RMS mic level, to calibrate input gain
    empirically instead of guessing at volume percentages.

    Aim for peak in roughly the 60-90% range with zero clipped samples while speaking at
    a normal, natural volume -- not shouting, not straining. Requires the optional `audio`
    extra (`pip install -e '.[audio]'`).
    """
    import numpy as np

    from .audio import capture
    from .audio.levels import measure_levels

    typer.echo(f"Recording {duration:.0f}s -- speak at your normal voice level throughout...")
    blocksize = 1600
    n_chunks = max(1, int(duration * capture.SAMPLE_RATE / blocksize))
    recorded = []
    with capture.open_stream(blocksize=blocksize) as stream:
        for _, chunk in zip(range(n_chunks), capture.frames(stream, blocksize)):
            recorded.append(chunk)

    report = measure_levels(np.concatenate(recorded))

    typer.echo(
        f"peak={report.peak_pct:.1f}%  rms={report.rms_pct:.1f}%  "
        f"clipped_samples={report.clipped_samples}"
    )
    if report.clipped:
        typer.echo("CLIPPING DETECTED -- lower your mic input gain.")
    elif report.peak_pct < 30:
        typer.echo("Peak is quite low -- consider raising your mic input gain.")
    elif report.peak_pct > 95:
        typer.echo("Peak is very close to the ceiling -- consider lowering gain slightly.")
    else:
        typer.echo("Looks like a reasonable level.")


if __name__ == "__main__":
    app()
