# Market target read ports and session evidence

## Goal

An evolution scan can read a registered non BitPro market target through stable read ports, and a sessions calendar uses complete, explicitly identified trading days in the target timezone for its 7+7 decision.

## Requirements

- FR-001: Inventory, source, session snapshot, fills, and return series used by an evolution scan come from the selected target read ports. BitPro's current read and decision behavior remains compatible.
- FR-002: A sessions target requires explicit exchange trading dates and timezone on every evidence point. Missing, duplicate, inconsistent, or ambiguous trading date evidence blocks the decision.
- FR-003: Session windows select 14 complete trading dates, split into two seven-session halves, and require comparable coverage at all boundaries. Non trading gaps are permitted only when the calendar declares them.
- FR-004: A non BitPro contract fixture reaches the scan's eligibility and degradation decision without writing to an external system.
- FR-005: API and Paper write port migration, platform server tools, and QuantLab live evidence remain separate unfinished work.
- FR-006: A registered standard MCP client routes canonical read tools through the typed read ports, validates source and target identity, and fails preflight when required source or calendar tools are absent.

## Success criteria

- SC-001: Targeted tests cover BitPro compatibility, a non BitPro scan through an offline MCP transport, sessions gap and timezone rejection, and a positive and negative degradation decision.
- SC-002: No budget, approval, cost, or live trading policy changes.
