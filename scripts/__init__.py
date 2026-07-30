"""Package boundary for standalone validation and controller modules.

Importing :mod:`scripts` must stay side-effect free.  Candidate identity and
native validation run before the controller catalog is activated, so importing
the controller here would make release tooling depend on mutable runtime state.
"""

__all__: list[str] = []
