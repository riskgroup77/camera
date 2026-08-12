from app.schemas.base import CamelModel


class SystemResourcesOut(CamelModel):
    cpu: int
    ram: int
    disk: int
