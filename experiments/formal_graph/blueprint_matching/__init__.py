"""Benchmark similarity metrics on apap blueprint↔formal slogan matching.

The grid is fixed:
  - Rows: blueprint informal statements that have a slogan in RDS.
  - Cols: formal (Lean) decls in the apap project that have a slogan in RDS.
  - Truth labels: ``statement_formalization`` rows with ``'blueprint' = ANY(methods)``.

See ``__main__.py`` for usage.
"""
