"""DA domain rules (G2PRegisterDomainServiceDA): formats, Ethiopian-calendar
age check and the web-intake-only required check.

Imports openg2p_registry_core, so it runs in the container, not on a bare host.
"""

import unittest

from openg2p_registry_core.errors import G2PRegistryException
from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA as Service,
)


_REQUIRED = {"first_name": "Name", "middle_name": "Father Name", "gender": "Gender", "email": "Email",
            "foundational_id": "Fayda ID (FAN)"}  # what widget-required in the metadata would give
REQUIRED = [("Contact", {"panels": [{"widgets": [
    {"widget": "input", "widget-label": label, "widget-required": True, "widget-data-path": f"reg.{field}"}
    for field, label in _REQUIRED.items()]}]}, False)]


def validate(record: dict) -> dict:
    """Run the synchronous checks in the order the service runs them."""
    Service._normalise_source(record)
    Service._validate_names(record)
    Service._validate_fayda_fan(record)
    Service._validate_phones(record)
    Service._validate_email(record)
    Service._validate_birth_ec(record)
    Service._validate_joined_date(record)
    Service._validate_required(record, REQUIRED)
    return record


class TestFormats(unittest.TestCase):
    def test_values_are_cleaned(self):
        record = validate({
            "foundational_id": "3234 5678-9014 0001", "mobile_number": "0911 22 33 44",
            "email": "A@B.ORG", "birth_month_ec": "4", "birth_year_ec": "1985",
        })
        self.assertEqual(record["foundational_id"], "3234567890140001")
        self.assertEqual(record["mobile_number"], "0911223344")
        self.assertEqual(record["email"], "a@b.org")
        self.assertEqual((record["birth_month_ec"], record["birth_year_ec"]), (4, 1985))

    def test_rejections_name_the_field(self):
        cases = [
            ({"foundational_id": "12345"}, "Fayda ID (FAN) must be exactly 16 digits"),
            ({"foundational_id": "556556221254"}, "Fayda ID (FAN) must be exactly 16 digits"),
            ({"telegram_number": "12345"}, "Telegram Number must be an Ethiopian phone number"),
            ({"email": "x@y"}, "Email is not a valid email address"),
            ({"first_name": "Abc123"}, "Name may contain only letters"),
            ({"birth_month_ec": 14, "birth_year_ec": 1985}, "Month of Birth (EC) must be from 1 to 13"),
        ]
        for record, message in cases:
            with self.subTest(record=record):
                with self.assertRaises(G2PRegistryException) as ctx:
                    validate(dict(record))
                self.assertIn(message, str(ctx.exception))


class TestRequired(unittest.TestCase):
    def test_web_intake_blank_required_field_is_rejected(self):
        with self.assertRaises(G2PRegistryException) as ctx:
            validate({"first_name": "Abebe", "email": "", "source": "WEB_INTAKE"})
        self.assertIn("Required: Contact: fill in Email", str(ctx.exception))

    def test_absent_key_is_a_partial_save_not_a_blank(self):
        validate({"first_name": "Abebe", "source": "WEB_INTAKE"})

    def test_import_rows_are_format_checked_only(self):
        record = validate({"first_name": "Abebe", "email": "", "source": "CSV_IMPORT"})
        self.assertIsNone(record["email"])

    def test_blank_source_is_dropped_so_the_column_default_applies(self):
        self.assertEqual(validate({"source": ""}), {})


if __name__ == "__main__":
    unittest.main()
