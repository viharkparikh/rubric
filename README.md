# rubric

Score yourself against a rubric you bring, using evidence instead of opinion.

Self-assessment surveys measure confidence. Ask a room of people to rate their
own capability at anything and you learn who is bold, not who is good. This
reads actual signals off your machine, matches them against a framework you
define, and tells you where you land and what would move you up.

```
$ python3 rubric.py score

Building with AI
Overall: 1.3

  Assisted work: Default (3)
    Evidence
      - ai_sessions=1481 (needs 400)

  Unattended automation: One scheduled job (1)
    Evidence
      - scheduled_jobs=1 (needs 1)
    To reach A few, with state
      - scheduled_jobs: 1 of 3
      - agents_with_state: 0 of 1
      - Add failure reporting. If it dies quietly you will trust it for
        four days too long.

  Knowing whether it works: Vibes (0)
    To reach Spot checks
      - eval_files: 0 of 1
      - Fix the set of cases so runs are comparable over time.
```

## The framework is yours

Nothing about any particular ladder is baked in. A framework is one TOML file
defining dimensions, levels, and the thresholds that separate them. Two
unrelated examples ship in `frameworks/`, deliberately so: one scores building
with AI, the other scores open source presence, and the engine cannot tell them
apart.

Write your own and drop it in that directory. Schema and design notes are in
[frameworks/README.md](frameworks/README.md).

## Setup

```bash
git clone https://github.com/<you>/rubric && cd rubric
python3 rubric.py init
```

`init` reads the framework you pick, works out which signals it scores on, and
asks how to measure each one. Five source types:

| Type | Measures |
|---|---|
| `filesystem` | count of paths matching a glob |
| `git` | repos and recent commits under a root |
| `scheduled` | launchd or cron jobs matching a pattern |
| `command` | any shell one-liner that prints a number |
| `manual` | a number you type, for evidence no command can see |

`command` is the one that keeps this generic. If you can express the evidence as
a shell one-liner, it is a signal:

```json
{ "type": "command", "signal": "external_users",
  "run": "gh api repos/me/thing -q .stargazers_count" }
```

A signal with no source is zero, so a half-configured framework degrades to a
low score rather than an error.

## Commands

```bash
python3 rubric.py init                 # interactive setup, writes config.json
python3 rubric.py scan                 # collect signals, print them raw
python3 rubric.py scan --format json
python3 rubric.py score                # collect and score
python3 rubric.py score --format markdown
python3 rubric.py score --format json  # for piping somewhere
```

Zero dependencies. Python 3.9+. Uses stdlib `tomllib` on 3.11 and up, and a
bundled parser for the TOML subset the schema needs on older versions, because
macOS still ships 3.9 and a self-assessment tool you cannot run is a poor
advertisement for itself.

## What this is not

**It is not a benchmark.** The thresholds in the bundled frameworks are guesses.
They are calibrated against one person's intuition, which is to say barely
calibrated at all. The number is only meaningful against itself over time.

**It cannot see quality.** Every signal is a count. It knows you have 1,481
sessions and nothing about whether any of them were any good. A framework built
on counts will reward volume, and you should assume it is being gamed the moment
anyone's performance review touches it.

**It is happiest measuring one person.** There is no aggregation, no comparison,
no leaderboard. That omission is deliberate: the moment this scores a team, the
counts become targets and the signal dies.

The honest use is as a mirror you point at yourself twice a year, with a
framework you wrote and disagree with slightly.

## Licence

MIT.
