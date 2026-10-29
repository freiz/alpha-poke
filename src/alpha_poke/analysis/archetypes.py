"""Team tables for the belief's priors: one row per team (one side of one game), its species and
whether it won. (The archetype clustering that lived here was unused and removed on 2026-10-28;
the belief's set archetypes are belief.sets.)"""

import pandas as pd


def team_table(mons: pd.DataFrame) -> pd.DataFrame:
    return (
        mons.groupby(["id", "side"])
        .agg(species=("species", list), won=("won", "first"))
        .reset_index()
    )
