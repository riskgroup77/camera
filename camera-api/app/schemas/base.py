from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for every schema exposed over the API.

    Serializes Python's snake_case field names as camelCase JSON keys,
    matching the frontend's TypeScript interfaces in camera/src/types/index.ts
    field-for-field (e.g. full_name -> fullName). FastAPI's response_model
    handling uses aliases by default, so routes need no extra config.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
