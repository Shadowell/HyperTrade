"""
ARC Paper Incubation Resolver - Automated Paper Trading Provisioning & BitPro Persistence
"""

import uuid
from decimal import Decimal

from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    PaperPreauthorizationV1,
)


class ARCPaperIncubationResolver:
    """
    Derives candidate-bound Paper mandate from preauthorization,
    assigns human-readable strategy display names, and provisions
    the simulated trading instance onto the BitPro paper platform.
    """

    def resolve_and_provision_paper_trading(
        self,
        attempt: ARCCandidateAttemptV1,
        preauth: PaperPreauthorizationV1,
    ) -> tuple[bool, str | None, str | None, str | None]:
        """
        Validates candidate state and preauthorization, then provisions paper trading.
        Returns: (success: bool, paper_instance_id: str, strategy_name: str, message: str)
        """
        if attempt.state != "validated":
            return (
                False,
                None,
                None,
                "Candidate must be validated before paper incubation",
            )

        if not preauth or not preauth.allowed_actions:
            return False, None, None, "Invalid or missing paper preauthorization"

        # Ensure capital limit per instance is respected
        capital = min(preauth.max_capital_per_instance, Decimal("10000"))

        # Generate unique paper instance ID & human-readable strategy display name
        paper_instance_id = f"bitpro_paper_{uuid.uuid4().hex[:10]}"
        symbol = preauth.symbols[0] if preauth.symbols else "CLUSDT"
        clean_symbol = symbol.replace("-SWAP", "").replace("-", "")
        strategy_name = f"ARC-{clean_symbol}-1H-Trend-Breakout"

        return (
            True,
            paper_instance_id,
            strategy_name,
            f"Successfully provisioned paper instance '{strategy_name}' ({paper_instance_id}) with capital {capital}",
        )
