from datetime import datetime
from typing import Any, Optional

from models.passport import ValidationResult


class ValidationService:
    """Validate extracted passport fields (checksum + date rules)."""

    def validate(
        self,
        mrz_data: dict[str, Any],
        date_of_issue: Optional[str],
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        checksum_valid = bool(mrz_data.get("checksum_valid"))
        has_core_fields = bool(
            mrz_data.get("surname")
            and mrz_data.get("date_of_birth")
            and mrz_data.get("date_of_expiry")
        )
        has_any_field = bool(
            mrz_data.get("surname")
            or mrz_data.get("given_name")
            or mrz_data.get("date_of_birth")
            or mrz_data.get("date_of_expiry")
        )

        if not checksum_valid:
            if has_core_fields:
                warnings.append(
                    "MRZ checksum failed - fields were extracted but may be unreliable "
                    "(common on specimen/test passports or low-quality scans)."
                )
            elif has_any_field:
                warnings.append(
                    "MRZ checksum could not be confirmed - some fields may be incomplete."
                )
            else:
                errors.append(
                    "MRZ checksum validation failed or could not be confirmed."
                )

        dob = mrz_data.get("date_of_birth")
        expiry = mrz_data.get("date_of_expiry")

        dob_dt = self._parse_iso(dob)
        issue_dt = self._parse_iso(date_of_issue)
        expiry_dt = self._parse_iso(expiry)

        if dob and dob_dt is None:
            errors.append(f"Invalid date_of_birth format: {dob}")
        if date_of_issue and issue_dt is None:
            errors.append(f"Invalid date_of_issue format: {date_of_issue}")
        if expiry and expiry_dt is None:
            errors.append(f"Invalid date_of_expiry format: {expiry}")

        if not date_of_issue:
            warnings.append("Date of issue could not be extracted from the visual zone.")

        if dob_dt and expiry_dt and not (dob_dt < expiry_dt):
            errors.append("date_of_birth must be before date_of_expiry.")

        if issue_dt and expiry_dt and not (expiry_dt > issue_dt):
            errors.append("date_of_expiry must be after date_of_issue.")

        if dob_dt and issue_dt and not (dob_dt < issue_dt):
            errors.append("date_of_birth must be before date_of_issue.")

        if not mrz_data.get("surname"):
            warnings.append("Surname is missing from MRZ.")
        if not mrz_data.get("given_name"):
            warnings.append("Given name is missing from MRZ.")

        dates_valid = (
            dob_dt is not None
            and expiry_dt is not None
            and (issue_dt is None or (
                expiry_dt > issue_dt and dob_dt < issue_dt
            ))
            and dob_dt < expiry_dt
            and not any("Invalid date" in e for e in errors)
            and not any("must be" in e for e in errors)
        )

        return ValidationResult(
            mrz_checksum_valid=checksum_valid,
            dates_valid=dates_valid,
            errors=errors,
            warnings=warnings,
        )

    def _parse_iso(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
