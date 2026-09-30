"""Automated backtest matrix and parameter self-optimization sandbox.

Provides parameter space definition, sampling strategies (Grid, Random, LLM),
multi-dimensional backtest matrix execution, Walk-Forward Overfitting Guard,
composite robustness scoring, and QuantLab / BitPro export capabilities.
"""

from __future__ import annotations
