import logging
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService

from .domain_validation_utils import as_int, parse_date, validation_error
from .ethiopian_calendar import gregorian_to_ethiopic
from .fayda_uniqueness import duplicate_message, find_fayda_owner
from .required_fields import DA_REGISTER_ID, describe, load_sections, problems
from ...geo_codes import geo_codes
from .validation_rules import (
    EMAIL_PATTERN,
    FAYDA_FAN_PATTERN,
    NAME_FIELD_LABELS,
    NAME_FIELDS,
    NAME_MAX_LENGTH,
    NAME_PATTERN,
    PHONE_FIELD_LABELS,
    PHONE_PATTERN,
    is_interactive,
    matches,
)

_logger = logging.getLogger("g2p-register-domain-service")


class G2PRegisterDomainServiceDA(G2PRegisterDomainService):
    """Domain rules for the DA register.

    Looked up by the platform through G2PRegisterDomainFactory as
    G2PRegisterDomainService<register mnemonic>, so the register mnemonic
    must be "DA".
    """

    async def validate_domain_attributes(self, records: list[dict]):
        sections = await load_sections(DA_REGISTER_ID) if records else []
        for record in records:
            self._normalise_source(record)
            self._validate_names(record)
            self._validate_fayda_fan(record)
            self._validate_phones(record)
            self._validate_email(record)
            self._validate_birth_ec(record)
            self._validate_joined_date(record)
            self._validate_required(record, sections)
            await self._check_fayda_unique(record)
            await self._sync_flattened_geo_names(record)

    # ------------------------------------------------------------ validation --
    @staticmethod
    def _normalise_source(record: dict) -> None:
        """Drop a blank source so an insert takes the column default
        (WEB_INTAKE) and an update leaves the stored value alone."""
        if "source" in record and not str(record.get("source") or "").strip():
            record.pop("source")

    @staticmethod
    def _validate_names(record: dict) -> None:
        for field in NAME_FIELDS:
            # An absent key is a partial update of other fields, not a blank.
            if field not in record:
                continue
            value = record.get(field)
            text = "" if value is None else str(value).strip()
            if not text:
                continue
            label = NAME_FIELD_LABELS.get(field, field)
            if len(text) > NAME_MAX_LENGTH:
                validation_error(f"{label} must be {NAME_MAX_LENGTH} characters or fewer")
            if not matches(NAME_PATTERN, text):
                validation_error(
                    f"{label} may contain only letters (Latin or Ethiopic), "
                    "spaces, hyphens and apostrophes"
                )
            record[field] = text

    @staticmethod
    def _validate_fayda_fan(record: dict) -> None:
        if "foundational_id" not in record:
            return
        value = record.get("foundational_id")
        text = "" if value is None else str(value).strip().replace(" ", "").replace("-", "")
        if not text:
            record["foundational_id"] = None
            return
        if not matches(FAYDA_FAN_PATTERN, text):
            validation_error("Fayda ID (FAN) must be exactly 16 digits")
        record["foundational_id"] = text

    @staticmethod
    def _validate_phones(record: dict) -> None:
        for field, label in PHONE_FIELD_LABELS.items():
            if field not in record:
                continue
            value = record.get(field)
            text = "" if value is None else str(value).strip().replace(" ", "").replace("-", "")
            if not text:
                record[field] = None
                continue
            if not matches(PHONE_PATTERN, text):
                validation_error(f"{label} must be an Ethiopian phone number, e.g. 0911234567")
            record[field] = text

    @staticmethod
    def _validate_email(record: dict) -> None:
        if "email" not in record:
            return
        value = record.get("email")
        text = "" if value is None else str(value).strip()
        if not text:
            record["email"] = None
            return
        if not matches(EMAIL_PATTERN, text):
            validation_error("Email is not a valid email address")
        record["email"] = text.lower()

    @staticmethod
    def _validate_birth_ec(record: dict) -> None:
        """Month / Year of Birth in the Ethiopian calendar: a real month, a
        4-digit year, not in the future and not more than 100 years back. No
        minimum age: the FSD sets none (decision of 28 Oct 2026)."""
        if "birth_month_ec" not in record and "birth_year_ec" not in record:
            return
        month = as_int(record.get("birth_month_ec")) if "birth_month_ec" in record else None
        year = as_int(record.get("birth_year_ec")) if "birth_year_ec" in record else None
        if "birth_month_ec" in record:
            if record.get("birth_month_ec") not in (None, "") and month is None:
                validation_error("Month of Birth (EC) must be a number from 1 to 13")
            if month is not None and not 1 <= month <= 13:
                validation_error("Month of Birth (EC) must be from 1 to 13")
            record["birth_month_ec"] = month
        if "birth_year_ec" in record:
            if record.get("birth_year_ec") not in (None, "") and year is None:
                validation_error("Year of Birth (EC) must be a 4-digit year")
            record["birth_year_ec"] = year
        if year is None:
            return
        today_y, today_m, _ = gregorian_to_ethiopic(date.today())
        if year < today_y - 100:
            validation_error("Year of Birth (EC) is too far in the past")
        # Months on the 13-month Ethiopian year; an unknown month counts as the
        # first one so a current-year birth is not refused as "future".
        if (today_y * 13 + today_m) - (year * 13 + (month or 1)) < 0:
            validation_error("Month / Year of Birth (EC) cannot be in the future")

    @staticmethod
    def _validate_joined_date(record: dict) -> None:
        joined = parse_date(record.get("joined_date"))
        if joined is not None and joined > date.today():
            validation_error("Joining Date cannot be in the future")

    @staticmethod
    def _validate_required(record: dict, sections: list) -> None:
        """Required fields (widget-required in the register metadata, with its
        show / hide / require conditions), checked only when a person fills in
        the form. Only keys present in the record are checked here: the intake
        form saves one section at a time, and a change request carries only
        what changed. Absent keys are the intake guard's job
        (required_fields_mixin.py) on save and finalize; imports and partner
        pushes are checked whole by their enrichers."""
        if not is_interactive(record):
            return
        found = []
        for name, schema, _is_list in sections:
            phrases = problems(schema, record, absent_is_missing=False)
            if phrases:
                found.append(describe(name, phrases))
        if found:
            validation_error("Required: " + "; ".join(found))

    # ------------------------------------------------------------------ geo --
    @staticmethod
    async def _check_fayda_unique(record: dict) -> None:
        """One DA per Fayda ID: refuse a Fayda ID another DA or another live
        submission already holds (see fayda_uniqueness)."""
        fayda_id = record.get("foundational_id")
        if not fayda_id:
            return
        registered, other = await find_fayda_owner(fayda_id, str(record.get("internal_record_id") or ""))
        message = duplicate_message(fayda_id, registered, other)
        if message:
            validation_error(message)

    async def _sync_flattened_geo_names(self, record: dict) -> None:
        """Flatten geo_code_hierarchy_json into region/zone/woreda/kebele_name
        so the list view and filters can use plain columns."""
        if "geo_lowest_level_value_id" not in record:
            return
        level_value_id = record.get("geo_lowest_level_value_id")
        levels = {"region": None, "zone": None, "woreda": None, "kebele": None}
        level_aliases = {
            "region": "region", "zone": "zone", "district": "zone",
            "woreda": "woreda", "ward": "woreda", "kebele": "kebele", "village": "kebele",
        }
        if level_value_id:
            from openg2p_registry_core.services import G2PGeoHierarchyService

            try:
                service = G2PGeoHierarchyService.get_component() or G2PGeoHierarchyService()
                hierarchy = await service.get_geo_hierarchy(level_value_id)
            except Exception as error:  # noqa: BLE001
                _logger.warning(f"Geo lookup for {level_value_id} failed, keeping stored names: {error}")
                if record.get("geo_code_hierarchy_json"):
                    record.update(geo_codes(record["geo_code_hierarchy_json"]))
                return
            if not (hierarchy or {}).get("hierarchy"):
                # Lookup failed (e.g. master data not reachable from this
                # worker): keep whatever names the record already carries, and
                # take the codes from the chain the record was saved with.
                if record.get("geo_code_hierarchy_json"):
                    record.update(geo_codes(record["geo_code_hierarchy_json"]))
                return
            for entry in hierarchy["hierarchy"]:
                mnemonic = (entry.get("level_mnemonic") or "").strip().lower()
                target = level_aliases.get(mnemonic)
                if target:
                    levels[target] = self._geo_display_name(entry)
        record["region_name"] = levels["region"]
        record["zone_name"] = levels["zone"]
        record["woreda_name"] = levels["woreda"]
        record["kebele_name"] = levels["kebele"]
        record.update(geo_codes(hierarchy if level_value_id else None))

    @staticmethod
    def _geo_display_name(entry: dict) -> str | None:
        for key in ("level_value_display_name", "level_value_name", "display_name"):
            value = str(entry.get(key) or "").strip()
            if value:
                return value
        mnemonic = str(entry.get("level_value_mnemonic") or "").strip()
        if not mnemonic:
            return None
        return mnemonic.replace("_", " ").replace("-", " ").title()

    # --------------------------------------------------- search / record name --
    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        keys = [
            "functional_record_id", "foundational_id",
            "first_name", "middle_name", "last_name",
            "mobile_number", "telegram_number", "alternate_number", "email",
            "education_level", "specialisation", "position",
            "region_name", "zone_name", "woreda_name", "kebele_name",
        ]
        parts = []
        if extra:
            parts.extend(str(v).strip() for v in extra if str(v).strip())
        parts.extend(
            str(payload.get(k) or "").strip() for k in keys if str(payload.get(k) or "").strip()
        )
        return " ".join(parts).strip()

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        keys = ["first_name", "middle_name", "last_name"]
        parts = []
        if extra:
            parts.extend(str(v).strip() for v in extra if str(v).strip())
        parts.extend(
            str(payload.get(k) or "").strip() for k in keys if str(payload.get(k) or "").strip()
        )
        return " ".join(parts).strip()
