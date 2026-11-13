"""Compatibility alias.

The Central Orchestrator Brain and the mission brain were two copies of the same
logic. There is now a single brain, ``foundry_brain.FoundryBrain``, which plans the
team, runs the specialists (as Foundry agents when provisioned) and performs the
five-point final validation. This module keeps the old import path working.
"""

from .foundry_brain import FoundryBrain as OrchestratorBrain

__all__ = ["OrchestratorBrain"]
