from pydantic import BaseModel


class Pagination:
    page: int
    limit: int
    total: int
    pages: int