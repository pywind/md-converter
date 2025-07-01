from pydantic import BaseModel

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool | None = None

class HealthStatus(BaseModel):
    status: str
    version: str

class FileInfo(BaseModel):
    filename: str
    content_type: str
    size: int

class ProcessingJob(BaseModel):
    job_id: str
    status: str
    created_at: str
    updated_at: str

class DatasetInfo(BaseModel):
    dataset_id: str
    name: str
    row_count: int
    column_count: int

class Configuration(BaseModel):
    setting_key: str
    setting_value: str