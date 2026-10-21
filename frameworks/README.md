# Writing a framework

A framework is one TOML file. Drop it in this directory and `rubric.py init`
will offer it.

```toml
name = "What this measures"
description = "Optional. Printed above the report."

[[dimension]]
id = "short_id"
name = "Human readable name"
weight = 1.0              # relative contribution to the overall number

  [[dimension.level]]
  score = 0
  label = "Where everyone starts"
  next = "Optional advice for reaching the level above this one."

  [[dimension.level]]
  score = 1
  label = "Next rung"
  requires = { some_signal = 5, other_signal = 1 }
  next = "..."
```

## How scoring works

A level is **met** when every entry in `requires` is satisfied, meaning the
collected signal is greater than or equal to the threshold. Your score for a
dimension is the highest level that is met. Levels are checked in ascending
order, so a level with no `requires` always passes and makes a sensible zero.

The overall number is the weighted mean of dimension scores. It is the least
interesting output and exists mostly so you can watch it move.

## Signals

Signal names are arbitrary strings. Whatever you reference in `requires`,
`init` will ask you how to measure. The `command` source type means anything
you can express as a shell one-liner that prints a number is usable:

```json
{ "type": "command", "signal": "external_users",
  "run": "gh api repos/:owner/:repo -q .stargazers_count" }
```

A signal with no source is zero, which means a half-configured framework
degrades to a low score rather than an error.

## Design notes

Three things worth getting right, learned by getting them wrong:

**Make the top level unreachable.** If the highest rung is achievable, the
framework stops being useful the moment someone reaches it. Better for the top
to read "you are past what this can measure, write your own."

**Weight the dimensions unevenly.** Equal weights imply the dimensions matter
equally, which is almost never true and quietly encourages people to farm the
easy one.

**Put the advice on the level above.** `next` on a level describes how to reach
*it*, not how to leave it. The report shows the gap and the advice together,
which is the only part anyone acts on.
