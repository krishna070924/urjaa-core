from pydantic import BaseModel


class CategoryBase(BaseModel):
    id: int
    name: str
    slug: str


class CategoryResponse(CategoryBase):
    class Config:
        orm_mode = True