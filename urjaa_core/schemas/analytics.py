"""Pydantic schemas for all analytics endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

class TopProduct(BaseModel):
    product_id: UUID
    name: str
    units_sold: int
    revenue: float


class AnalyticsOverviewResponse(BaseModel):
    revenue_this_month: float
    revenue_last_month: float
    revenue_change_pct: float | None
    orders_this_month: int
    orders_last_month: int
    avg_order_value: float
    new_customers_this_month: int
    top_5_products: list[TopProduct]


# ---------------------------------------------------------------------------
# Customer overview
# ---------------------------------------------------------------------------

class CustomerOverviewResponse(BaseModel):
    total_customers: int
    new_this_month: int
    active_30d: int
    at_risk: int
    churned: int
    avg_lifetime_value: float


# ---------------------------------------------------------------------------
# At-risk customers
# ---------------------------------------------------------------------------

class AtRiskCustomer(BaseModel):
    id: UUID
    name: str
    email: str
    whatsapp_number: str | None
    last_purchase_date: datetime | None
    days_since_purchase: int | None
    total_spend: float
    wishlist_count: int
    last_seen_at: datetime | None


class AtRiskCustomersResponse(BaseModel):
    customers: list[Any]  # AtRiskCustomer or AtRiskCustomerWithChannel
    total: int


# ---------------------------------------------------------------------------
# Churned customers
# ---------------------------------------------------------------------------

class ChurnedCustomer(BaseModel):
    id: UUID
    name: str
    email: str
    whatsapp_number: str | None
    last_order_date: datetime | None
    total_historical_spend: float
    wishlist_count: int
    created_at: datetime


class ChurnedCustomersResponse(BaseModel):
    customers: list[ChurnedCustomer]
    total: int


# ---------------------------------------------------------------------------
# Customer profile (360 view)
# ---------------------------------------------------------------------------

class OrderSummary(BaseModel):
    id: UUID
    status: str
    amount: float
    created_at: datetime
    item_count: int


class WishlistItem(BaseModel):
    product_id: UUID
    product_name: str
    days_in_wishlist: int
    price: float | None


class RecentView(BaseModel):
    product_id: UUID
    product_name: str
    viewed_at: datetime


class TicketSummary(BaseModel):
    id: UUID
    subject: str
    status: str
    priority: str
    created_at: datetime


class RFMResult(BaseModel):
    r_score: int
    f_score: int
    m_score: int
    segment: str
    total_spend: float
    last_order_date: datetime | None


class CustomerProfileResponse(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str | None
    whatsapp_number: str | None
    date_of_birth: date | None
    created_at: datetime
    last_seen_at: datetime | None
    total_orders: int
    total_spend: float
    avg_order_value: float
    orders: list[OrderSummary]
    wishlist_items: list[WishlistItem]
    recently_viewed: list[RecentView]
    support_tickets: list[TicketSummary]
    rfm_score: RFMResult | None


# ---------------------------------------------------------------------------
# Demographics
# ---------------------------------------------------------------------------

class AgeBucket(BaseModel):
    bucket: str
    count: int


class CityCount(BaseModel):
    city: str
    count: int


class DemographicsResponse(BaseModel):
    age_distribution: list[AgeBucket]
    city_distribution: list[CityCount]
    customers_with_age_data: int
    total_customers: int


# ---------------------------------------------------------------------------
# Products — trending
# ---------------------------------------------------------------------------

class TrendingProduct(BaseModel):
    product_id: UUID
    name: str
    count: int
    category: str | None


class ConversionProduct(BaseModel):
    product_id: UUID
    name: str
    view_count: int
    purchase_count: int
    conversion_rate: float
    category: str | None


class TrendingProductsResponse(BaseModel):
    period: str
    by_views: list[TrendingProduct]
    by_cart_adds: list[TrendingProduct]
    by_conversion: list[ConversionProduct]


# ---------------------------------------------------------------------------
# Best sellers
# ---------------------------------------------------------------------------

class BestSellerProduct(BaseModel):
    product_id: UUID
    name: str
    category: str | None
    units_sold: int
    revenue: float
    avg_price: float
    stock_remaining: int


class BestSellersResponse(BaseModel):
    period: str
    products: list[BestSellerProduct]


# ---------------------------------------------------------------------------
# Wishlist stale
# ---------------------------------------------------------------------------

class WishlistStaleProduct(BaseModel):
    product_id: UUID
    name: str
    category: str | None
    price: float | None
    stock_quantity: int
    user_count: int
    avg_days_in_wishlist: float


class WishlistStaleResponse(BaseModel):
    min_days: int
    products: list[WishlistStaleProduct]


# ---------------------------------------------------------------------------
# Abandoned products
# ---------------------------------------------------------------------------

class AbandonedProduct(BaseModel):
    product_id: UUID
    name: str
    add_to_cart_count: int
    purchase_count: int
    abandon_rate_pct: float


class AbandonedProductsResponse(BaseModel):
    products: list[AbandonedProduct]


# ---------------------------------------------------------------------------
# Price ranges
# ---------------------------------------------------------------------------

class PriceRangeBucket(BaseModel):
    bucket_label: str
    view_count: int
    purchase_count: int
    conversion_pct: float
    revenue: float


class PriceRangesResponse(BaseModel):
    buckets: list[PriceRangeBucket]


# ---------------------------------------------------------------------------
# Search insights
# ---------------------------------------------------------------------------

class QueryCount(BaseModel):
    query: str
    count: int


class SearchInsightsResponse(BaseModel):
    zero_result_queries: list[QueryCount]
    top_queries: list[QueryCount]
    click_through_rate: float
    total_searches: int


# ---------------------------------------------------------------------------
# ML — RFM
# ---------------------------------------------------------------------------

class RFMUserResult(BaseModel):
    user_id: UUID
    r_score: int
    f_score: int
    m_score: int
    segment: str
    total_spend: float
    last_order_date: datetime | None


class RFMSegmentCount(BaseModel):
    segment: str
    count: int


class RFMOverviewResponse(BaseModel):
    segments: list[RFMSegmentCount]
    champions: list[RFMUserResult]
    total_scored: int


# ---------------------------------------------------------------------------
# ML — Product affinity
# ---------------------------------------------------------------------------

class FeatureImportance(BaseModel):
    feature: str
    coefficient: float


class AffinityResponse(BaseModel):
    model_accuracy: float
    sample_size: int
    top_positive_features: list[FeatureImportance]
    top_negative_features: list[FeatureImportance]


class InsufficientDataResponse(BaseModel):
    message: str
    sample_size: int


# ---------------------------------------------------------------------------
# ML — Cohorts
# ---------------------------------------------------------------------------

class CohortRow(BaseModel):
    month: str
    size: int
    retention: list[float]


class CohortResponse(BaseModel):
    cohorts: list[CohortRow]
    max_periods: int


# ---------------------------------------------------------------------------
# Cache stats
# ---------------------------------------------------------------------------

class CacheStatsResponse(BaseModel):
    stats: dict[str, Any]


# ---------------------------------------------------------------------------
# Store vs Website comparison
# ---------------------------------------------------------------------------

class ChannelTopProduct(BaseModel):
    product_id: UUID
    name: str
    revenue: float
    units_sold: int


class ChannelStats(BaseModel):
    revenue: float
    orders: int
    avg_order_value: float
    top_5_products: list[ChannelTopProduct]


class TotalStats(BaseModel):
    revenue: float
    orders: int


class StoreVsWebsiteResponse(BaseModel):
    store: ChannelStats
    website: ChannelStats
    total: TotalStats


# ---------------------------------------------------------------------------
# Store overview
# ---------------------------------------------------------------------------

class PeakSlot(BaseModel):
    slot: int  # 0-23 for hours, 0-6 for dow
    count: int


class StoreOverviewResponse(BaseModel):
    store_revenue_30d: float
    store_orders_30d: int
    repeat_customer_count: int
    repeat_customer_rate: float
    avg_transaction_store: float
    avg_transaction_website: float
    peak_hours: list[PeakSlot]
    peak_days: list[PeakSlot]


# ---------------------------------------------------------------------------
# Store behavior (customer channel split)
# ---------------------------------------------------------------------------

class ChannelCustomer(BaseModel):
    id: UUID
    name: str
    email: str
    whatsapp_number: str | None
    total_spend: float


class StoreBehaviorResponse(BaseModel):
    store_only_count: int
    website_only_count: int
    both_channels_count: int
    store_only_sample: list[ChannelCustomer]
    website_only_sample: list[ChannelCustomer]


# ---------------------------------------------------------------------------
# At-risk with primary channel
# ---------------------------------------------------------------------------

class AtRiskCustomerWithChannel(AtRiskCustomer):
    primary_channel: str  # 'store' | 'website' | 'both'
