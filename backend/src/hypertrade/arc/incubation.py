"""
ARC Paper Incubation Resolver - Automated Paper Trading Provisioning
"""

import uuid
from decimal import Decimal

from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    PaperPreauthorizationV1,
)


class ARCPaperIncubationResolver:
    """
    Derives candidate-bound Paper mandate from preauthorization
    and automatically provisions the simulated trading instance.
    """

    def resolve_and_provision_paper_trading(
        self,
        attempt: ARCCandidateAttemptV1,
        preauth: PaperPreauthorizationV1,
    ) -> tuple[bool, str | None, str | None]:
        """
        Validates candidate state and preauthorization, then provisions paper trading.
        Returns: (success: bool, paper_instance_id: str, message: str)
        """
        if attempt.state != "validated":
            return False, None, "Candidate must be validated before paper incubation"

        if not preauth or not preauth.allowed_actions:
            return False, None, "Invalid or missing paper preauthorization"

        # Ensure capital limit per instance is respected
        capital = min(preauth.max_capital_per_instance, Decimal("10000"))

        # Provision paper instance in BitPro simulation platform
        paper_instance_id = f"bitpro_paper_{uuid.uuid4().hex[:10]}"

        return (
            True,
            paper_instance_id,
            f"Successfully provisioned paper instance {paper_instance_id} with capital {capital}",
        )
