from datetime import datetime
from pydantic import BaseModel


class Assignment(BaseModel):
    assignment_id: str
    course_name: str
    assignment_name: str
    due_at: datetime | None
    url: str
