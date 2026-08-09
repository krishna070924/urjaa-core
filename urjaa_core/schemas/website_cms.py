from typing import Any

from pydantic import BaseModel, Field


class CMSImageAsset(BaseModel):
    url: str = ""
    alt: str = ""


class CMSHeroCTA(BaseModel):
    label: str = ""
    href: str = "/products"


class CMSHeader(BaseModel):
    announcement_text: str = ""
    enabled: bool = True


class CMSHeroItem(BaseModel):
    headline: str = ""
    description: str = ""
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)
    cta: CMSHeroCTA = Field(default_factory=CMSHeroCTA)


class CMSHeroAtelierNoteRow(BaseModel):
    label: str = ""
    value: str = ""
    highlight: bool = False


class CMSHeroAtelierNote(BaseModel):
    enableAtelierNote: bool = True
    title: str = "Atelier Note"
    description: str = ""
    display_type: str = "info"
    rows: list[CMSHeroAtelierNoteRow] = Field(default_factory=list)
    icon: str | None = None


class CMSHeroTag(BaseModel):
    text: str = ""
    link: str = ""
    style: str = "default"


class CMSHeroTags(BaseModel):
    enableTags: bool = True
    tags: list[CMSHeroTag] = Field(default_factory=list)


class CMSHeroSection(BaseModel):
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    cta_text: str = ""
    cta_link: str = "/products"
    items: list[CMSHeroItem] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    atelier_note: CMSHeroAtelierNote = Field(default_factory=CMSHeroAtelierNote)
    hero_tags: CMSHeroTags = Field(default_factory=CMSHeroTags)


class CMSCategoryItem(BaseModel):
    id: int
    name: str = ""
    slug: str = ""
    caption: str = ""
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)


class CMSCategoriesSection(BaseModel):
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    items: list[CMSCategoryItem] = Field(default_factory=list)


class CMSCategoriesGridItem(BaseModel):
    id: int
    name: str = ""
    slug: str = ""
    caption: str = ""
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)


class CMSPriceBucketItem(BaseModel):
    title: str = ""
    subtitle: str = ""
    min_price: int = 0
    max_price: int = 0
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)


class CMSPriceBucketsSection(BaseModel):
    enabled: bool = True
    title: str = ""
    items: list[CMSPriceBucketItem] = Field(default_factory=list)


class CMSCollectionItem(BaseModel):
    id: int
    slug: str = ""
    title: str = ""
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)


class CMSCollectionsSection(BaseModel):
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    items: list[CMSCollectionItem] = Field(default_factory=list)


class CMSListSection(BaseModel):
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    items: list[Any] = Field(default_factory=list)


class CMSTrustBarItem(BaseModel):
    icon: str = ""
    title: str = ""
    subtitle: str = ""


class CMSTrustBarSection(BaseModel):
    enabled: bool = True
    title: str = ""
    subtitle: str = ""
    items: list[CMSTrustBarItem] = Field(default_factory=list)


class CMSBrandStory(BaseModel):
    enabled: bool = True
    title: str = ""
    description: str = ""
    image: CMSImageAsset = Field(default_factory=CMSImageAsset)


class CMSCTASection(BaseModel):
    text: str = ""
    link: str = "/products"


class WebsiteCMSHomepageResponse(BaseModel):
    schema_version: str = "2.0.0"
    header: CMSHeader = Field(default_factory=CMSHeader)
    hero: CMSHeroSection = Field(default_factory=CMSHeroSection)
    categories: CMSCategoriesSection = Field(default_factory=CMSCategoriesSection)
    categories_grid: list[CMSCategoriesGridItem] = Field(default_factory=list)
    price_buckets: CMSPriceBucketsSection = Field(default_factory=CMSPriceBucketsSection)
    collections: CMSCollectionsSection = Field(default_factory=CMSCollectionsSection)
    trust_bar: CMSTrustBarSection = Field(default_factory=CMSTrustBarSection)
    occasions: CMSListSection = Field(default_factory=CMSListSection)
    bestsellers: CMSListSection = Field(default_factory=CMSListSection)
    bestsellers_enabled: bool = True
    brand_story: CMSBrandStory = Field(default_factory=CMSBrandStory)
    cta_section: CMSCTASection = Field(default_factory=CMSCTASection)
    sections: list[dict[str, Any]] = Field(default_factory=list)
