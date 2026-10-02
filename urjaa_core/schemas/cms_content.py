"""N-03: CMS content schemas for the Home and Our Story pages.

D38 (launch scope): Home is media + product selection ONLY — no free text
anywhere in `HomePageContent`. Our Story gets heading/body/photo per section
(fixed order), with a structured list for the "What We Believe" section.

Every `*_url` field here is either empty/None or an http(s) URL that is
literally under the configured `MEDIA_BASE_URL` (our own uploads) — this is
the one validation choke point that keeps `javascript:` URLs and arbitrary
third-party hosts out of admin-authored, publicly-rendered content.
"""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from urjaa_core.core.config import settings


def _check_media_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    base = settings.media_base_url.rstrip("/")
    # Prefix match against our configured media host is both necessary and
    # sufficient: it already pins the scheme (MEDIA_BASE_URL is http(s)),
    # the host (no third-party domains), and the path (no javascript:, no
    # data:, no open redirects through this host).
    if value != base and not value.startswith(base + "/"):
        raise ValueError(f"URL must be one of our own uploads, under {base}")
    return value


def _require_media_url(value: str) -> str:
    checked = _check_media_url(value)
    if not checked:
        raise ValueError("A media URL is required")
    return checked


# Optional media URL: None/"" collapse to None.
MediaUrl = Annotated[str | None, AfterValidator(_check_media_url)]
# Required media URL: must resolve to a non-empty, validated URL.
RequiredMediaUrl = Annotated[str, AfterValidator(_require_media_url)]


def _no_duplicates(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate ids are not allowed")
    return values


# =============================================================================
# Home page
# =============================================================================

class HeroContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: Literal["image", "video"]
    media_url: RequiredMediaUrl
    poster_url: MediaUrl = None


class ShopByCategoryTile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: int
    image_url: MediaUrl = None


class DeckContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: Annotated[list[UUID], Field(max_length=6), AfterValidator(_no_duplicates)] = Field(
        default_factory=list
    )


class ImageSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_url: MediaUrl = None


class ExclusiveOffersContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 3 fixed photo slots — no text (D38). The component's copy for each
    # slot is static/code-owned until a future text-enabled release.
    slots: list[ImageSlot] = Field(default_factory=lambda: [ImageSlot(), ImageSlot(), ImageSlot()])

    @field_validator("slots")
    @classmethod
    def _exactly_three(cls, value: list[ImageSlot]) -> list[ImageSlot]:
        if len(value) != 3:
            raise ValueError("exclusive_offers needs exactly 3 slots")
        return value


class BestSellersContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: Annotated[list[UUID], Field(max_length=8), AfterValidator(_no_duplicates)] = Field(
        default_factory=list
    )


class CuratedCollectionsTile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: int
    image_url: MediaUrl = None


class CuratedCollectionsContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Component renders a fixed 7/5-col layout for exactly 4 collections.
    tiles: list[CuratedCollectionsTile] = Field(default_factory=list)

    @field_validator("tiles")
    @classmethod
    def _exactly_four(cls, value: list[CuratedCollectionsTile]) -> list[CuratedCollectionsTile]:
        if len(value) != 4:
            raise ValueError("curated_collections needs exactly 4 tiles")
        ids = [tile.collection_id for tile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate collection ids are not allowed")
        return value


class ForHerHimContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    her_image_url: MediaUrl = None
    him_image_url: MediaUrl = None


class ShopByOccasionContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # D38 launch scope only covers photos for these 4 named occasions — the
    # component currently renders 6 cards; the other 2 (wedding guest,
    # celebrations) stay on their built-in design assets until a later slice.
    bridal: MediaUrl = None
    festive: MediaUrl = None
    gifting: MediaUrl = None
    everyday: MediaUrl = None


class StoneStoryTile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stone_id: int
    image_url: MediaUrl = None


class StoneStoriesContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The component hardcodes exactly 4 stone cards (name/description are
    # static copy, D38 no-text). Tiles carry real `stones.id` FKs (validated
    # against the DB at save time) rather than free-text names, so the admin
    # editor and storefront both key off a stable id. Default content maps
    # these 4 cards to real stone rows: Emerald=4, Blue Sapphire=5 (card says
    # "SAPPHIRE"), Pearl=7 (card says "BASRA PEARL"), Polki=2 (card says
    # "POLKI DIAMOND" — the uncut-diamond *cut*, which this DB tracks as its
    # own stone distinct from generic Diamond=1). See N-03 contract doc.
    tiles: list[StoneStoryTile] = Field(default_factory=list)

    @field_validator("tiles")
    @classmethod
    def _exactly_four(cls, value: list[StoneStoryTile]) -> list[StoneStoryTile]:
        if len(value) != 4:
            raise ValueError("stone_stories needs exactly 4 tiles")
        ids = [tile.stone_id for tile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate stone ids are not allowed")
        return value


class CuratedByUrjaaContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # D39: Curated by Urjaa = 3 products.
    product_ids: Annotated[list[UUID], Field(max_length=3), AfterValidator(_no_duplicates)] = Field(
        default_factory=list
    )


class CraftsmanshipContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slots: list[ImageSlot] = Field(default_factory=lambda: [ImageSlot(), ImageSlot()])

    @field_validator("slots")
    @classmethod
    def _exactly_two(cls, value: list[ImageSlot]) -> list[ImageSlot]:
        if len(value) != 2:
            raise ValueError("craftsmanship needs exactly 2 slots")
        return value


class HomePageContent(BaseModel):
    """D38: media + product selection only, no text anywhere. Field order
    here is the page's section order (shop-by-budget/trust-strip/concierge
    carry no CMS content and are omitted entirely)."""

    model_config = ConfigDict(extra="forbid")

    hero: HeroContent
    shop_by_category: Annotated[list[ShopByCategoryTile], Field(max_length=8)] = Field(default_factory=list)
    deck: DeckContent = Field(default_factory=DeckContent)
    exclusive_offers: ExclusiveOffersContent = Field(default_factory=ExclusiveOffersContent)
    best_sellers: BestSellersContent = Field(default_factory=BestSellersContent)
    curated_collections: CuratedCollectionsContent
    for_her_him: ForHerHimContent = Field(default_factory=ForHerHimContent)
    shop_by_occasion: ShopByOccasionContent = Field(default_factory=ShopByOccasionContent)
    stone_stories: StoneStoriesContent
    curated_by_urjaa: CuratedByUrjaaContent = Field(default_factory=CuratedByUrjaaContent)
    craftsmanship: CraftsmanshipContent = Field(default_factory=CraftsmanshipContent)

    @field_validator("shop_by_category")
    @classmethod
    def _unique_categories(cls, value: list[ShopByCategoryTile]) -> list[ShopByCategoryTile]:
        ids = [tile.category_id for tile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate category ids are not allowed")
        return value


# =============================================================================
# Our Story page
# =============================================================================

class OurStorySection(BaseModel):
    """Generic section shape (D38): heading, body text, optional photo.
    `body` is plain text — paragraphs are whatever the author split on a
    blank line; we only cap length, we don't store/accept markup."""

    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=4000)
    image_url: MediaUrl = None

    @field_validator("heading", "body")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


class BeliefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=600)


class OurStoryBeliefsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=4000)
    beliefs: list[BeliefItem] = Field(min_length=1, max_length=6)


class OurStoryContent(BaseModel):
    """Fixed section order per D38, mirroring the storefront page exactly:
    opening, introduction, journey, workbench, hands, beliefs, emblem,
    ancestral roots, next chapter."""

    model_config = ConfigDict(extra="forbid")

    opening: OurStorySection
    introduction: OurStorySection
    journey: OurStorySection
    workbench: OurStorySection
    hands: OurStorySection
    beliefs: OurStoryBeliefsSection
    emblem: OurStorySection
    ancestral_roots: OurStorySection
    next_chapter: OurStorySection
