"""Radiographer physics core — runs unchanged natively and in Pyodide (WASM).

Public surface:

* :mod:`engine.bridge` — JSON-text facade across the Pyodide boundary
  (``solve`` / ``evaluate`` / ``chain`` / ``release``).
* :class:`engine.inventory.SolvedInventory` — the solve-once / evaluate-many core.
* :func:`engine.chain.build_dag` — decay-chain DAG (nodes + edges).
"""

from __future__ import annotations

from engine.inventory import EngineError, SolvedInventory

__all__ = ["EngineError", "SolvedInventory"]
