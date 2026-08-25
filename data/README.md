# data/

```
private/     embargoed collaboration material - NOT in version control
synthetic/   invented fixture, safe to publish, structurally identical
```

`guardrail_eval.config.resolve()` prefers `private/` and falls back to
`synthetic/`, so the same commands work with or without access.

Generate the fixture with:

```bash
python tools/make_synthetic_fixture.py
```

See `../docs/DATA_AVAILABILITY.md`. The synthetic content is **not clinical
guidance** and **not the study's data**.
