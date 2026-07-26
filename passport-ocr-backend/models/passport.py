from typing import Optional

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    mrz_checksum_valid: bool = False
    dates_valid: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PassportExtractResponse(BaseModel):
    surname: Optional[str] = None
    given_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    date_of_issue: Optional[str] = None
    date_of_expiry: Optional[str] = None
    validation: ValidationResult = Field(default_factory=ValidationResult)
    raw_mrz: Optional[dict] = None
