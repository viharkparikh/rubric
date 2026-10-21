#!/usr/bin/env python3
"""rubric — score yourself against a rubric you bring, using evidence instead of opinion.

Self-assessment surveys measure confidence, not capability. This reads actual
signals off your machine (repos, scheduled jobs, session history, or the output
of any command you name), matches them against a framework you define, and
reports where you land plus what would move you up a level.

The framework is external and arbitrary. Nothing about AI, engineering, or any
particular ladder is baked in. Ship your own TOML and the tool scores it.

    python3 rubric.py init                    interactive setup
    python3 rubric.py scan                    collect signals, print them
    python3 rubric.py score                   collect and score
    python3 rubric.py score --format markdown

Zero dependencies, Python 3.9+. Uses stdlib tomllib on 3.11 and up, and a small
bundled parser for the TOML subset the framework schema uses on older versions,
because macOS still ships 3.9 and a self-assessment tool you cannot run is a
poor advertisement for itself.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None
    from minitoml import loads as _minitoml_loads

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


# ---------------------------------------------------------------------------
# Collectors. Each takes a source spec from config.json and returns signals:
# a flat dict of name -> number. Everything downstream is thresholds on numbers,
# which keeps the framework format simple and the collectors independent.
# ---------------------------------------------------------------------------


def collect_filesystem(spec: dict) -> dict:
    """Count paths matching globs.

    {"type": "filesystem", "signal": "agents", "roots": ["~/agents"],
     "glob": "*/run.sh"}
    """
    total = 0
    for root in spec.get("roots", []):
        base = pathlib.Path(root).expanduser()
        if not base.exists():
            continue
        total += sum(1 for _ in base.glob(spec.get("glob", "*")))
    return {spec["signal"]: total}


def collect_git(spec: dict) -> dict:
    """Repo count and recent commit count under a set of roots.

    {"type": "git", "signal": "repos", "roots": ["~/dev"], "days": 90}
    """
    name = spec["signal"]
    days = int(spec.get("days", 90))
    repos = 0
    commits = 0
    for root in spec.get("roots", []):
        base = pathlib.Path(root).expanduser()
        if not base.exists():
            continue
        for gitdir in base.rglob(".git"):
            if not gitdir.is_dir():
                continue
            repos += 1
            out = _run(
                ["git", "-C", str(gitdir.parent), "log",
                 f"--since={days}.days", "--oneline"]
            )
            commits += len(out.splitlines()) if out else 0
    return {name: repos, f"{name}_commits": commits}


def collect_scheduled(spec: dict) -> dict:
    """Count scheduled jobs matching a pattern, on launchd or cron.

    {"type": "scheduled", "signal": "cron_jobs", "match": "agent"}
    """
    pattern = spec.get("match", "")
    found = 0
    plist_dir = pathlib.Path("~/Library/LaunchAgents").expanduser()
    if plist_dir.exists():
        found += sum(1 for p in plist_dir.glob("*.plist") if pattern in p.name)
    crontab = _run(["crontab", "-l"])
    if crontab:
        found += sum(1 for line in crontab.splitlines()
                     if pattern in line and not line.strip().startswith("#"))
    return {spec["signal"]: found}


def collect_command(spec: dict) -> dict:
    """Run any command, pull a number out of stdout.

    {"type": "command", "signal": "prs", "run": "gh pr list --author @me | wc -l"}

    The escape hatch that keeps this tool generic. If you can express the
    evidence as a shell one-liner, it is a signal.
    """
    out = _run(spec["run"], shell=True)
    if out is None:
        return {spec["signal"]: 0}
    if pattern := spec.get("extract"):
        match = re.search(pattern, out)
        raw = match.group(1) if match else "0"
    else:
        raw = out.strip().splitlines()[-1] if out.strip() else "0"
    try:
        return {spec["signal"]: float(re.sub(r"[^\d.\-]", "", raw) or 0)}
    except ValueError:
        return {spec["signal"]: 0}


def collect_manual(spec: dict) -> dict:
    """A number you supply, for evidence no command can see.

    {"type": "manual", "signal": "talks_given", "value": 2}

    Declared in config rather than asked at scan time, so a scheduled run is
    still reproducible. `init` is what fills these in.
    """
    return {spec["signal"]: float(spec.get("value", 0))}


COLLECTORS = {
    "filesystem": collect_filesystem,
    "git": collect_git,
    "scheduled": collect_scheduled,
    "command": collect_command,
    "manual": collect_manual,
}


def _run(cmd, shell: bool = False) -> str | None:
    try:
        result = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=60
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None


# ---------------------------------------------------------------------------
# Framework and scoring
# ---------------------------------------------------------------------------


@dataclass
class Level:
    score: int
    label: str
    requires: dict = field(default_factory=dict)
    next: str = ""


@dataclass
class Dimension:
    id: str
    name: str
    weight: float
    levels: list[Level]


@dataclass
class Framework:
    name: str
    description: str
    dimensions: list[Dimension]


def load_framework(path: pathlib.Path) -> Framework:
    if tomllib is not None:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    else:
        raw = _minitoml_loads(path.read_text())
    dimensions = []
    for d in raw.get("dimension", []):
        levels = [
            Level(
                score=int(lv["score"]),
                label=lv.get("label", str(lv["score"])),
                requires=lv.get("requires", {}),
                next=lv.get("next", ""),
            )
            for lv in d.get("level", [])
        ]
        levels.sort(key=lambda lv: lv.score)
        dimensions.append(
            Dimension(
                id=d["id"],
                name=d.get("name", d["id"]),
                weight=float(d.get("weight", 1.0)),
                levels=levels,
            )
        )
    return Framework(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        dimensions=dimensions,
    )


def level_met(level: Level, signals: dict) -> tuple[bool, list[str]]:
    """A level is met when every requirement passes. Returns the evidence too,
    because a score without its evidence is just an opinion with a number on it.
    """
    evidence = []
    for signal, threshold in level.requires.items():
        actual = signals.get(signal, 0)
        if actual < threshold:
            return False, []
        evidence.append(f"{signal}={_fmt(actual)} (needs {_fmt(threshold)})")
    return True, evidence


def score_dimension(dim: Dimension, signals: dict):
    achieved = dim.levels[0] if dim.levels else None
    evidence: list[str] = []
    for level in dim.levels:
        met, ev = level_met(level, signals)
        if met:
            achieved, evidence = level, ev
    nxt = next((lv for lv in dim.levels
                if achieved and lv.score > achieved.score), None)
    gaps = []
    if nxt:
        for signal, threshold in nxt.requires.items():
            actual = signals.get(signal, 0)
            if actual < threshold:
                gaps.append(f"{signal}: {_fmt(actual)} of {_fmt(threshold)}")
    return achieved, evidence, nxt, gaps


def _fmt(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"No config.json. Run: python3 {pathlib.Path(__file__).name} init")
    return json.loads(CONFIG_PATH.read_text())


def gather(config: dict) -> dict:
    signals: dict = {}
    for source in config.get("sources", []):
        collector = COLLECTORS.get(source.get("type"))
        if not collector:
            print(f"warning: unknown source type {source.get('type')!r}", file=sys.stderr)
            continue
        try:
            signals.update(collector(source))
        except Exception as exc:  # a broken source should not kill the run
            print(f"warning: source {source.get('signal')!r} failed: {exc}",
                  file=sys.stderr)
            signals.setdefault(source.get("signal", "unknown"), 0)
    return signals


def cmd_scan(args) -> None:
    signals = gather(load_config())
    if args.format == "json":
        print(json.dumps(signals, indent=2))
        return
    width = max((len(k) for k in signals), default=0)
    for key in sorted(signals):
        print(f"  {key:<{width}}  {_fmt(signals[key])}")


def cmd_score(args) -> None:
    config = load_config()
    framework = load_framework(
        pathlib.Path(config["framework"]).expanduser()
        if pathlib.Path(config["framework"]).expanduser().exists()
        else ROOT / config["framework"]
    )
    signals = gather(config)

    results = [(d, *score_dimension(d, signals)) for d in framework.dimensions]
    total = sum(d.weight for d, *_ in results) or 1
    overall = sum(
        (a.score if a else 0) * d.weight for d, a, *_ in results
    ) / total

    if args.format == "json":
        print(json.dumps({
            "framework": framework.name,
            "overall": round(overall, 2),
            "signals": signals,
            "dimensions": [
                {"id": d.id, "score": a.score if a else 0,
                 "label": a.label if a else "", "evidence": ev,
                 "next": n.label if n else None, "gaps": g}
                for d, a, ev, n, g in results
            ],
        }, indent=2))
        return

    md = args.format == "markdown"
    h1, h2, bullet = ("# ", "## ", "- ") if md else ("", "  ", "  - ")

    print(f"{h1}{framework.name}")
    if framework.description:
        print(f"\n{framework.description}")
    print(f"\nOverall: {overall:.1f}\n")

    for dim, achieved, evidence, nxt, gaps in results:
        label = achieved.label if achieved else "unscored"
        score = achieved.score if achieved else 0
        print(f"{h2}{dim.name}: {label} ({score})")
        if evidence:
            print(f"\n{'Evidence' if md else '  Evidence'}")
            for item in evidence:
                print(f"{bullet}{item}")
        if nxt:
            print(f"\n{'To reach' if md else '  To reach'} {nxt.label}")
            for gap in gaps:
                print(f"{bullet}{gap}")
            if nxt.next:
                print(f"{bullet}{nxt.next}")
        print()


def cmd_init(args) -> None:
    """The setup form. Walks the available frameworks and sources, writes config."""
    print("rubric setup\n")

    frameworks = sorted((ROOT / "frameworks").glob("*.toml"))
    if not frameworks:
        sys.exit("No frameworks found in frameworks/.")

    print("Frameworks:")
    for i, path in enumerate(frameworks, 1):
        fw = load_framework(path)
        print(f"  {i}. {fw.name} — {len(fw.dimensions)} dimensions")
    print("\nBring your own by dropping a .toml in frameworks/. "
          "See frameworks/README.md for the schema.")
    choice = _ask("\nWhich framework", "1")
    try:
        framework = frameworks[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit("Not a valid choice.")

    fw = load_framework(framework)
    needed = sorted({
        signal
        for dim in fw.dimensions
        for level in dim.levels
        for signal in level.requires
    })

    print(f"\n{fw.name} scores on {len(needed)} signals. "
          "Tell me how to measure each one.\n")
    print("  1 filesystem  count files matching a glob")
    print("  2 git         repos and recent commits under a root")
    print("  3 scheduled   launchd or cron jobs matching a pattern")
    print("  4 command     any shell one-liner that prints a number")
    print("  5 manual      a number you type now")
    print("  6 skip        leave at zero\n")

    sources = []
    for signal in needed:
        kind = _ask(f"{signal}", "6")
        if kind in ("6", "skip", ""):
            continue
        if kind in ("1", "filesystem"):
            sources.append({
                "type": "filesystem", "signal": signal,
                "roots": [r.strip() for r in _ask("  roots (comma separated)", "~").split(",")],
                "glob": _ask("  glob", "*"),
            })
        elif kind in ("2", "git"):
            sources.append({
                "type": "git", "signal": signal,
                "roots": [r.strip() for r in _ask("  roots (comma separated)", "~").split(",")],
                "days": int(_ask("  commit window in days", "90")),
            })
        elif kind in ("3", "scheduled"):
            sources.append({
                "type": "scheduled", "signal": signal,
                "match": _ask("  name contains", "agent"),
            })
        elif kind in ("4", "command"):
            sources.append({
                "type": "command", "signal": signal,
                "run": _ask("  command"),
            })
        elif kind in ("5", "manual"):
            sources.append({
                "type": "manual", "signal": signal,
                "value": float(_ask("  value", "0") or 0),
            })

    config = {
        "framework": str(framework.relative_to(ROOT)),
        "sources": sources,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"\nWrote {CONFIG_PATH.name} with {len(sources)} sources.")
    print(f"Next: python3 {pathlib.Path(__file__).name} score")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return answer or default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="interactive setup")
    p_init.set_defaults(func=cmd_init)

    p_scan = sub.add_parser("scan", help="collect and print raw signals")
    p_scan.add_argument("--format", choices=["text", "json"], default="text")
    p_scan.set_defaults(func=cmd_scan)

    p_score = sub.add_parser("score", help="collect signals and score them")
    p_score.add_argument("--format", choices=["text", "markdown", "json"],
                         default="text")
    p_score.set_defaults(func=cmd_score)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9+ required.")
    main()
