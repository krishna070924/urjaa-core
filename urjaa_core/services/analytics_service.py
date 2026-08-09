"""Analytics intelligence service — Phase 3.

Provides RFM scoring, product affinity regression, cohort analysis, and
wishlist decay analysis. All results are cached in-memory with a 1-hour TTL.

Import guard: pandas/scikit-learn are optional — if not installed the ML
functions return None gracefully. Install via:
    pip install pandas>=2.2.0 scikit-learn>=1.5.0 numpy>=1.26.0
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 3600  # 1 hour

_cache: dict[str, dict[str, Any]] = {}
_cache_hits: dict[str, int] = {}
_cache_misses: dict[str, int] = {}
_cache_last_refresh: dict[str, float] = {}


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        _cache_misses[key] = _cache_misses.get(key, 0) + 1
        return None
    if time.time() - entry["ts"] > _CACHE_TTL_SECONDS:
        del _cache[key]
        _cache_misses[key] = _cache_misses.get(key, 0) + 1
        return None
    _cache_hits[key] = _cache_hits.get(key, 0) + 1
    return entry["value"]


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = {"value": value, "ts": time.time()}
    _cache_last_refresh[key] = time.time()


def clear_cache() -> None:
    """Force-clear all cached analytics results."""
    _cache.clear()
    logger.info("analytics_service: cache cleared")


def get_analytics_cache_stats() -> dict[str, Any]:
    """Return cache hit/miss counts and last refresh times."""
    result: dict[str, Any] = {}
    all_keys = set(_cache_hits) | set(_cache_misses) | set(_cache_last_refresh)
    for key in all_keys:
        last = _cache_last_refresh.get(key)
        result[key] = {
            "hits": _cache_hits.get(key, 0),
            "misses": _cache_misses.get(key, 0),
            "last_refresh": datetime.fromtimestamp(last, UTC).isoformat() if last else None,
            "cached": key in _cache,
        }
    return result


# ---------------------------------------------------------------------------
# RFM types
# ---------------------------------------------------------------------------

class RFMResult:
    def __init__(
        self,
        user_id: UUID,
        r_score: int,
        f_score: int,
        m_score: int,
        segment: str,
        total_spend: float,
        last_order_date: datetime | None,
    ) -> None:
        self.user_id = user_id
        self.r_score = r_score
        self.f_score = f_score
        self.m_score = m_score
        self.segment = segment
        self.total_spend = total_spend
        self.last_order_date = last_order_date

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "r_score": self.r_score,
            "f_score": self.f_score,
            "m_score": self.m_score,
            "segment": self.segment,
            "total_spend": self.total_spend,
            "last_order_date": self.last_order_date.isoformat() if self.last_order_date else None,
        }


def _r_score(days_since: int) -> int:
    if days_since <= 7:
        return 5
    if days_since <= 30:
        return 4
    if days_since <= 60:
        return 3
    if days_since <= 90:
        return 2
    return 1


def _f_score(order_count: int) -> int:
    if order_count >= 10:
        return 5
    if order_count >= 5:
        return 4
    if order_count >= 3:
        return 3
    if order_count >= 2:
        return 2
    return 1


def _segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 3:
        return "Loyal"
    if f == 1 and r >= 4:
        return "New"
    if r <= 2 and f >= 2:
        return "At Risk"
    if r == 1 and f == 1:
        return "Lost"
    return "Potential"


# ---------------------------------------------------------------------------
# FUNCTION 1: compute_rfm_scores
# ---------------------------------------------------------------------------

def compute_rfm_scores(store_id: UUID, db: Any) -> dict[UUID, RFMResult]:
    """Compute RFM scores for all customers of a store. Cached 1 hour."""
    cache_key = f"rfm:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from sqlalchemy import func
        from urjaa_core.models.order import Order

        now = datetime.now(UTC)

        rows = (
            db.query(
                Order.user_id,
                func.max(Order.created_at).label("last_order"),
                func.count(Order.id).label("order_count"),
                func.sum(Order.total_amount).label("total_spend"),
            )
            .filter(Order.user_id.isnot(None), Order.store_id == store_id)
            .group_by(Order.user_id)
            .all()
        )

        if not rows:
            _cache_set(cache_key, {})
            return {}

        # Compute monetary quintiles
        try:
            import numpy as np
            spends = [float(r.total_spend or 0) for r in rows]
            quintiles = np.percentile(spends, [20, 40, 60, 80])
        except ImportError:
            quintiles = None

        def _m_score(spend: float) -> int:
            if quintiles is None:
                # Fallback: simple thresholds
                if spend >= 100000:
                    return 5
                if spend >= 50000:
                    return 4
                if spend >= 20000:
                    return 3
                if spend >= 5000:
                    return 2
                return 1
            if spend >= quintiles[3]:
                return 5
            if spend >= quintiles[2]:
                return 4
            if spend >= quintiles[1]:
                return 3
            if spend >= quintiles[0]:
                return 2
            return 1

        result: dict[UUID, RFMResult] = {}
        for row in rows:
            last_dt = row.last_order
            if last_dt and hasattr(last_dt, "tzinfo") and last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            days_since = (now - last_dt).days if last_dt else 999

            r = _r_score(days_since)
            f = _f_score(int(row.order_count or 1))
            spend = float(row.total_spend or 0)
            m = _m_score(spend)
            seg = _segment(r, f, m)

            result[row.user_id] = RFMResult(
                user_id=row.user_id,
                r_score=r,
                f_score=f,
                m_score=m,
                segment=seg,
                total_spend=spend,
                last_order_date=last_dt,
            )

        _cache_set(cache_key, result)
        return result

    except Exception:
        logger.exception("analytics_service: compute_rfm_scores failed")
        return {}


# ---------------------------------------------------------------------------
# FUNCTION 2: compute_rfm_for_user
# ---------------------------------------------------------------------------

def compute_rfm_for_user(user_id: UUID, store_id: UUID, db: Any) -> RFMResult | None:
    """Single-user RFM. Reuses cached compute_rfm_scores result."""
    scores = compute_rfm_scores(store_id, db)
    return scores.get(user_id)


# ---------------------------------------------------------------------------
# FUNCTION 3: compute_product_affinity
# ---------------------------------------------------------------------------

def compute_product_affinity(store_id: UUID, db: Any) -> dict[str, Any] | None:
    """Logistic regression on purchase conversion."""
    cache_key = f"affinity:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
        from urjaa_core.models.product_view_event import ProductViewEvent
        from urjaa_core.models.sale import Sale
        from urjaa_core.models.product import Product
        from urjaa_core.models.product_variant import ProductVariant
        from sqlalchemy import func

        # Negative samples: views
        view_rows = (
            db.query(
                ProductViewEvent.product_id,
                ProductViewEvent.viewed_at,
                Product.featured,
                Product.subcategory_id,
                ProductVariant.metal_type,
                ProductVariant.price_override,
            )
            .join(Product, Product.id == ProductViewEvent.product_id)
            .outerjoin(ProductVariant, ProductVariant.product_id == ProductViewEvent.product_id)
            .filter(ProductViewEvent.store_id == store_id)
            .distinct(ProductViewEvent.id)
            .limit(5000)
            .all()
        )

        # Positive samples: sales
        sale_rows = (
            db.query(
                Sale.product_id,
                Sale.date_time,
                Sale.final_price,
                Product.featured,
                Product.subcategory_id,
                ProductVariant.metal_type,
            )
            .join(Product, Product.id == Sale.product_id)
            .outerjoin(ProductVariant, ProductVariant.id == Sale.variant_id)
            .filter(Sale.store_id == store_id, Sale.status == "COMPLETED")
            .limit(5000)
            .all()
        )

        if len(view_rows) + len(sale_rows) < 50:
            result = {"insufficient_data": True, "sample_size": len(view_rows) + len(sale_rows)}
            _cache_set(cache_key, result)
            return result

        def price_bucket(price: float | None) -> str:
            if not price:
                return "unknown"
            if price < 2500:
                return "<2500"
            if price < 5000:
                return "2500-5000"
            if price < 10000:
                return "5000-10000"
            if price < 25000:
                return "10000-25000"
            if price < 50000:
                return "25000-50000"
            return ">50000"

        rows_data = []
        for r in view_rows:
            rows_data.append({
                "target": 0,
                "price_bucket": price_bucket(float(r.price_override) if r.price_override else None),
                "subcategory_id": str(r.subcategory_id) if r.subcategory_id else "unknown",
                "metal_type": str(r.metal_type) if r.metal_type else "unknown",
                "day_of_week": r.viewed_at.weekday() if r.viewed_at else 0,
                "is_featured": int(bool(r.featured)),
            })
        for r in sale_rows:
            rows_data.append({
                "target": 1,
                "price_bucket": price_bucket(float(r.final_price) if r.final_price else None),
                "subcategory_id": str(r.subcategory_id) if r.subcategory_id else "unknown",
                "metal_type": str(r.metal_type) if r.metal_type else "unknown",
                "day_of_week": r.date_time.weekday() if r.date_time else 0,
                "is_featured": int(bool(r.featured)),
            })

        df = pd.DataFrame(rows_data)
        y = df["target"].values

        feature_df = pd.get_dummies(
            df[["price_bucket", "subcategory_id", "metal_type", "day_of_week", "is_featured"]],
            columns=["price_bucket", "subcategory_id", "metal_type"],
        )
        feature_names = list(feature_df.columns)
        X = feature_df.values

        model = LogisticRegression(max_iter=500, C=1.0)
        model.fit(X, y)

        from sklearn.model_selection import cross_val_score
        try:
            cv_scores = cross_val_score(model, X, y, cv=3, scoring="accuracy")
            accuracy = float(cv_scores.mean())
        except Exception:
            accuracy = float(model.score(X, y))

        coefs = list(zip(feature_names, model.coef_[0]))
        coefs_sorted = sorted(coefs, key=lambda x: x[1], reverse=True)

        top_positive = [{"feature": f, "coefficient": round(c, 4)} for f, c in coefs_sorted[:10] if c > 0]
        top_negative = [{"feature": f, "coefficient": round(c, 4)} for f, c in coefs_sorted[-10:] if c < 0]

        result = {
            "model_accuracy": round(accuracy, 4),
            "sample_size": len(rows_data),
            "top_positive_features": top_positive,
            "top_negative_features": top_negative,
            "insufficient_data": False,
        }
        _cache_set(cache_key, result)
        return result

    except ImportError:
        logger.warning("analytics_service: pandas/scikit-learn not installed — affinity unavailable")
        return None
    except Exception:
        logger.exception("analytics_service: compute_product_affinity failed")
        return None


# ---------------------------------------------------------------------------
# FUNCTION 4: compute_customer_cohorts
# ---------------------------------------------------------------------------

def compute_customer_cohorts(store_id: UUID, db: Any) -> dict[str, Any]:
    """Monthly cohort retention analysis."""
    cache_key = f"cohorts:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        import pandas as pd
        from urjaa_core.models.order import Order
        from sqlalchemy import func, extract

        rows = (
            db.query(
                Order.user_id,
                Order.created_at,
            )
            .filter(Order.user_id.isnot(None), Order.store_id == store_id)
            .order_by(Order.user_id, Order.created_at)
            .all()
        )

        if not rows:
            result = {"cohorts": [], "max_periods": 0}
            _cache_set(cache_key, result)
            return result

        data = [{"user_id": str(r.user_id), "created_at": r.created_at} for r in rows]
        df = pd.DataFrame(data)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["order_month"] = df["created_at"].dt.to_period("M")

        # Cohort month = first purchase month per user
        first_purchase = df.groupby("user_id")["order_month"].min().rename("cohort_month")
        df = df.join(first_purchase, on="user_id")
        df["period_number"] = (df["order_month"] - df["cohort_month"]).apply(lambda x: x.n)

        # Limit to last 12 cohort months
        now = pd.Timestamp.now(tz="UTC").to_period("M")
        twelve_months_ago = now - 12
        df = df[df["cohort_month"] >= twelve_months_ago]

        cohort_sizes = df[df["period_number"] == 0].groupby("cohort_month")["user_id"].nunique()

        # Filter out cohorts with < 10 customers
        cohort_sizes = cohort_sizes[cohort_sizes >= 10]

        max_periods = 12
        cohort_list = []

        for cohort_month in sorted(cohort_sizes.index):
            size = int(cohort_sizes[cohort_month])
            cohort_df = df[df["cohort_month"] == cohort_month]
            retention = []
            for period in range(max_periods + 1):
                active = cohort_df[cohort_df["period_number"] == period]["user_id"].nunique()
                retention.append(round(active / size * 100, 1))

            cohort_list.append({
                "month": str(cohort_month),
                "size": size,
                "retention": retention,
            })

        result = {"cohorts": cohort_list, "max_periods": max_periods}
        _cache_set(cache_key, result)
        return result

    except ImportError:
        logger.warning("analytics_service: pandas not installed — cohorts unavailable")
        return {"cohorts": [], "max_periods": 0}
    except Exception:
        logger.exception("analytics_service: compute_customer_cohorts failed")
        return {"cohorts": [], "max_periods": 0}


# ---------------------------------------------------------------------------
# FUNCTION 5: compute_wishlist_decay
# ---------------------------------------------------------------------------

def compute_wishlist_decay(store_id: UUID, db: Any) -> dict[str, Any]:
    """Wishlist decay analysis — hot/cold flagging."""
    cache_key = f"wishlist_decay:{store_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        from sqlalchemy import func
        from urjaa_core.models.wishlist import Wishlist
        from urjaa_core.models.product import Product
        from urjaa_core.models.product_variant import ProductVariant

        now = datetime.now(UTC)

        rows = (
            db.query(
                Wishlist.product_id,
                Product.name,
                func.count(Wishlist.id).label("user_count"),
                func.avg(
                    func.extract("epoch", func.now() - Wishlist.created_at) / 86400
                ).label("avg_days"),
                func.sum(ProductVariant.stock_quantity).label("stock"),
            )
            .join(Product, Product.id == Wishlist.product_id)
            .outerjoin(ProductVariant, ProductVariant.product_id == Wishlist.product_id)
            .group_by(Wishlist.product_id, Product.name)
            .all()
        )

        hot_items = []
        cold_items = []
        all_avg_days = []

        for r in rows:
            avg_days = float(r.avg_days or 0)
            user_count = int(r.user_count or 0)
            stock = int(r.stock or 0)
            all_avg_days.append(avg_days)

            item = {
                "product_id": str(r.product_id),
                "name": r.name,
                "user_count": user_count,
                "avg_days_in_wishlist": round(avg_days, 1),
                "stock": stock,
            }

            if user_count > 5 and stock < 10:
                hot_items.append(item)
            elif avg_days > 30 and stock > 20:
                cold_items.append(item)

        avg_global = sum(all_avg_days) / len(all_avg_days) if all_avg_days else 0.0

        result = {
            "hot_items": sorted(hot_items, key=lambda x: x["user_count"], reverse=True),
            "cold_items": sorted(cold_items, key=lambda x: x["avg_days_in_wishlist"], reverse=True),
            "avg_days_in_wishlist": round(avg_global, 1),
        }
        _cache_set(cache_key, result)
        return result

    except Exception:
        logger.exception("analytics_service: compute_wishlist_decay failed")
        return {"hot_items": [], "cold_items": [], "avg_days_in_wishlist": 0.0}
