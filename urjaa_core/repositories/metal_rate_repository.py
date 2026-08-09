from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from urjaa_core.models.metal_rate import MetalRate


class MetalRateRepository:

    @staticmethod
    def get_latest_rate(db: Session, base_metal_id: int, *, as_of: datetime | None = None):
        """Latest rate that is already effective, ignoring future-dated rows.

        URJ-066: a future-dated row must not price the catalog before it takes
        effect. "Now" is evaluated by the DATABASE (func.current_timestamp())
        rather than by Python, so the comparison stays in the same timezone frame
        the database used to store effective_from — a naive TIMESTAMP whose
        wall-clock depends on the Postgres session TimeZone. Comparing it against
        a naive Python datetime.utcnow() would wrongly drop the *current* rate
        (blacking out the whole catalog) on any non-UTC session. `as_of` overrides
        the clock for deterministic tests.
        """
        cutoff = as_of if as_of is not None else func.current_timestamp()
        return (
            db.query(MetalRate)
            .filter(MetalRate.base_metal_id == base_metal_id)
            .filter(MetalRate.effective_from <= cutoff)
            .order_by(MetalRate.effective_from.desc(), MetalRate.id.desc())
            .first()
        )
