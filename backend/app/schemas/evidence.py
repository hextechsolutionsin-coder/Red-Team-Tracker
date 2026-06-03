"""
Pydantic schemas for evidence file endpoints.

Requirements: 6.1, 6.5
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class EvidenceResponse(BaseModel):
    """
    Outgoing JSON representation of an evidence file record.

    Excludes the internal ``stored_filename`` path — clients receive only the
    original filename and metadata.  File content is served via the download
    endpoint.
    """

    id: uuid.UUID
    finding_id: uuid.UUID
    original_filename: str
    file_size_bytes: int
    mime_type: str
    uploaded_by: uuid.UUID
    uploaded_at: datetime

    model_config = {"from_attributes": True}
