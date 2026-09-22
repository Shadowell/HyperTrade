# Plan

1. Extend the target read port contracts to carry source, session, fills, equity identity and explicit trading dates. Add BitPro and canonical MCP adapters at the target boundary.
2. Route EvolutionService scan reads and source recheck through the selected read port. Keep the existing BitPro diagnostic and benchmark behavior.
3. Add sessions calendar window calculation and evidence validation in the feedback and continuation path. Retain the continuous branch exactly for BitPro.
4. Verify with direct and offline MCP transport non BitPro fixtures plus existing focused suites; run the full repository gate only when the coordinator provides an exclusive window.

The API and Paper provision ports are outside this slice.
