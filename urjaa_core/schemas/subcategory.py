from pydantic import BaseModel


class SubcategoryBase(BaseModel):
    id: int
    name: str
    slug: str


class SubcategoryResponse(SubcategoryBase):
    class Config:
        orm_mode = True