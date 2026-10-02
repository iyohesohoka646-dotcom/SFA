# Research case library

Run from the repository root with the installed package and your scientific interpreter:

```powershell
python -X utf8 examples/research/cases/run_cases.py --output .work/case-evidence
cdaf studio --project .work/case-evidence/matrix/success
```

The runner refuses an existing source destination. Each case has independent
success and failure projects, saved source, configuration, run, probe calls and
results. `--case matrix` selects one pair. Reopen its project in Web or desktop;
objects require an explicit double click or context-menu action to open data.

| Case | Successful evidence | Failure evidence |
|---|---|---|
| matrix | Numeric overlay, signed heatmap and named time/condition axes | NaN detected |
| table | Column meanings, units and expected shape | Unexpected row count |
| functions | Two real invocations, input/output and cumulative timing | Explicit zero timing budget fails |
| controls | Actual branch/loop summary and bounded numeric result | Out-of-range result |
| structure | File-level structure coverage | Dynamic callback target is unknown |
| combination | Separate previews and exact matrix multiplication | Incompatible inner dimensions |
| program | Enabled, hashed local program checks frozen evidence | Required input count fails |
| skill | Imported Skill, scoped environment and honest offline result | Missing Skill produces a visible error |

The Skill case defaults to **offline**, so its successful result is `unknown`
with an offline receipt; it does not claim a model interpretation. To perform
inference, configure a profile in that project’s model settings and pass
`--provider PROFILE`. Model and Skill opinions remain separate from numerical
checks. The runner’s `inference_sent` means inference was requested; inspect
the saved context receipt to verify whether an actual request completed.

`functions` timing includes instrumentation and observation overhead. Control
counts describe loop body entries. Original sources can also run directly with
`python matrix.py --failure`; this does not collect workbench evidence.
