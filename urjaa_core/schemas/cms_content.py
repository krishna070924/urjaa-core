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

# Fixed site pages a hero button may open (no free URLs: nothing to mistype
# or to point off-site).
HERO_PAGES = {
    "all_jewellery": "/collections",
    "new_arrivals": "/collections?sort=newest",
    "best_sellers": "/collections?sort=best_selling",
    "book_appointment": "/book-appointment",
    "our_story": "/our-story",
}


class HeroSlideLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["collection", "category", "page"]
    id: int | None = None
    page: Literal["all_jewellery", "new_arrivals", "best_sellers", "book_appointment", "our_story"] | None = None

    @model_validator(mode="after")
    def _target_matches_kind(self):
        if self.kind == "page":
            if self.page is None:
                raise ValueError("Choose which page this opens")
        elif self.id is None:
            raise ValueError(f"Choose which {self.kind} this opens")
        return self


def _text(limit: int):
    # None = show the designed text; "" = hide this line.
    return Field(default=None, max_length=limit)


class HeroButton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = _text(40)
    link: HeroSlideLink | None = None


class HeroSpotlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eyebrow: str | None = _text(60)
    text: str | None = _text(240)
    footnote: str | None = _text(60)


class HeroSlide(BaseModel):
    """O-02/D41 slide. Text fields: None = the designed text, "" = hidden.
    show_text False = media only, no overlay at all."""

    model_config = ConfigDict(extra="forbid")

    media_type: Literal["image", "video"]
    media_url: RequiredMediaUrl
    poster_url: MediaUrl = None
    # Whole-slide click target (optional).
    link: HeroSlideLink | None = None
    show_text: bool = True
    eyebrow: str | None = _text(80)
    location_line: str | None = _text(80)
    headline: str | None = _text(80)
    headline_accent: str | None = _text(80)
    body: str | None = _text(400)
    primary_button: HeroButton | None = None
    secondary_button: HeroButton | None = None
    spotlight: HeroSpotlight | None = None

    def links(self) -> list["HeroSlideLink"]:
        found = [self.link]
        for button in (self.primary_button, self.secondary_button):
            if button:
                found.append(button.link)
        return [link for link in found if link is not None]


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
    """D42: automatic — up to 8 active products tagged "Bestseller", resolved
    at storefront-read time (see cms_service.resolve_home_for_storefront).
    No admin-editable content; the manual `product_ids` picker this used to
    carry is gone (old saved rows that still have it are tolerated — see
    cms_service._normalize_home_raw, which drops the field on read)."""

    model_config = ConfigDict(extra="forbid")


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
        # 0 = keep the designed tiles; otherwise the component's fixed 4.
        if len(value) not in (0, 4):
            raise ValueError("curated_collections needs either no tiles or exactly 4")
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
        # 0 = keep the designed tiles; otherwise the component's fixed 4.
        if len(value) not in (0, 4):
            raise ValueError("stone_stories needs either no tiles or exactly 4")
        ids = [tile.stone_id for tile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate stone ids are not allowed")
        return value


class CuratedByUrjaaContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # D40 (supersedes D39's 3): Curated by Urjaa = up to 8 products.
    product_ids: Annotated[list[UUID], Field(max_length=8), AfterValidator(_no_duplicates)] = Field(
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

    # D41: hero is a carousel, 0-8 slides. [] = keep the designed hero.
    # Only slide 1 (index 0) may be a video; slide 1's link is optional,
    # every photo slide after it must carry a link.
    hero_slides: Annotated[list[HeroSlide], Field(max_length=8)] = Field(default_factory=list)
    shop_by_category: Annotated[list[ShopByCategoryTile], Field(max_length=8)] = Field(default_factory=list)
    deck: DeckContent = Field(default_factory=DeckContent)
    exclusive_offers: ExclusiveOffersContent = Field(default_factory=ExclusiveOffersContent)
    best_sellers: BestSellersContent = Field(default_factory=BestSellersContent)
    curated_collections: CuratedCollectionsContent = Field(default_factory=CuratedCollectionsContent)
    for_her_him: ForHerHimContent = Field(default_factory=ForHerHimContent)
    shop_by_occasion: ShopByOccasionContent = Field(default_factory=ShopByOccasionContent)
    stone_stories: StoneStoriesContent = Field(default_factory=StoneStoriesContent)
    curated_by_urjaa: CuratedByUrjaaContent = Field(default_factory=CuratedByUrjaaContent)
    craftsmanship: CraftsmanshipContent = Field(default_factory=CraftsmanshipContent)

    @field_validator("shop_by_category")
    @classmethod
    def _unique_categories(cls, value: list[ShopByCategoryTile]) -> list[ShopByCategoryTile]:
        ids = [tile.category_id for tile in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate category ids are not allowed")
        return value

    @field_validator("hero_slides")
    @classmethod
    def _validate_hero_slides(cls, value: list[HeroSlide]) -> list[HeroSlide]:
        for i, slide in enumerate(value):
            if i == 0:
                continue
            if slide.media_type == "video":
                raise ValueError("Only the first hero slide may be a video")
        return value


# =============================================================================
# Our Story page
# =============================================================================

def _story_text(limit: int):
    # O-07: every line on Our Story is editable. None = the designed text,
    # "" = hidden. Plain text only (paragraphs split on blank lines).
    return Field(default=None, max_length=limit)


class OurStorySection(BaseModel):
    """Common shape: small label above the heading, heading, body, photo."""

    model_config = ConfigDict(extra="forbid")

    eyebrow: str | None = _story_text(60)
    heading: str | None = _story_text(150)
    body: str | None = _story_text(4000)
    image_url: MediaUrl = None


class OurStoryOpening(OurStorySection):
    scroll_hint: str | None = _story_text(40)


class FounderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = _story_text(80)
    role: str | None = _story_text(80)
    image_url: MediaUrl = None


class PillarItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = _story_text(60)
    text: str | None = _story_text(400)


class OurStoryJourney(OurStorySection):
    founders: list[FounderItem] = Field(default_factory=list, max_length=4)
    pillars_eyebrow: str | None = _story_text(60)
    pillars_heading: str | None = _story_text(120)
    pillars: list[PillarItem] = Field(default_factory=list, max_length=6)


class StatItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = _story_text(20)
    label: str | None = _story_text(40)


class OurStoryWorkbench(OurStorySection):
    stats: list[StatItem] = Field(default_factory=list, max_length=4)


class OurStoryHands(OurStorySection):
    image_caption: str | None = _story_text(120)
    tags: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=6)


class BeliefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = _story_text(120)
    text: str | None = _story_text(600)


class OurStoryBeliefsSection(OurStorySection):
    beliefs: list[BeliefItem] = Field(default_factory=list, max_length=6)


class OurStoryEmblem(OurStorySection):
    caption: str | None = _story_text(120)


class OurStoryAncestralRoots(OurStorySection):
    image_caption: str | None = _story_text(80)
    button_label: str | None = _story_text(40)


class OurStoryNextChapter(OurStorySection):
    primary_button_label: str | None = _story_text(40)
    secondary_button_label: str | None = _story_text(40)


class OurStoryContent(BaseModel):
    """Fixed section order per D38, mirroring the storefront page exactly:
    opening, introduction, journey, workbench, hands, beliefs, emblem,
    ancestral roots, next chapter."""

    model_config = ConfigDict(extra="forbid")

    # Lists: [] = the designed items; a list replaces them wholesale.
    opening: OurStoryOpening = Field(default_factory=OurStoryOpening)
    introduction: OurStorySection = Field(default_factory=OurStorySection)
    journey: OurStoryJourney = Field(default_factory=OurStoryJourney)
    workbench: OurStoryWorkbench = Field(default_factory=OurStoryWorkbench)
    hands: OurStoryHands = Field(default_factory=OurStoryHands)
    beliefs: OurStoryBeliefsSection = Field(default_factory=OurStoryBeliefsSection)
    emblem: OurStoryEmblem = Field(default_factory=OurStoryEmblem)
    ancestral_roots: OurStoryAncestralRoots = Field(default_factory=OurStoryAncestralRoots)
    next_chapter: OurStoryNextChapter = Field(default_factory=OurStoryNextChapter)
