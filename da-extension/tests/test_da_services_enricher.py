"""DAServicesEnricherService: a DA pushed by DA Services (Frappe) -> DA fields.

Master Data lookups are stubbed. Imports the extension, so it runs in the container.
"""

import unittest
from unittest import mock

from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import g2p_da_enricher_services as module
from openg2p_registry_da_extension.register_domain.services import required_fields as rf

# What the register metadata and Master Data would answer (see code_lists.py).
FIELD_ATTRIBUTES = {"prefix": "PREFIX", "gender": "GENDER", "marital_status": "MARITAL_STATUS",
                    "education_level": "DA_EDUCATION_LEVEL", "specialisation": "DA_SPECIALISATION", "position": "DA_POSITION"}
FIELD_LABELS = {"prefix": "Salutation", "gender": "Gender", "marital_status": "Marital Status",
                "education_level": "Education Level", "specialisation": "Specialisation", "position": "Position"}
LISTS = {
    "PREFIX": {"MR": "Mr", "MRS": "Mrs", "MISS": "Miss", "MS": "Ms", "DR": "Dr"},
    "GENDER": {"FEMALE": "Female", "MALE": "Male", "OTHER": "Other", "UNKNOWN": "Unknown"},
    "MARITAL_STATUS": {"SINGLE": "Single", "MARRIED": "Married", "WIDOWED": "Widowed", "DIVORCED": "Divorced"},
    "DA_EDUCATION_LEVEL": {"CERTIFICATE": "Certificate", "DIPLOMA": "Diploma", "DEGREE": "Degree", "MASTERS": "Masters"},
    "DA_SPECIALISATION": {"CROP_PRODUCTION": "Crop production", "LIVESTOCK": "Livestock", "NATURAL_RESOURCES": "Natural resources",
                          "AGRONOMY": "Agronomy", "HORTICULTURE": "Horticulture", "OTHER": "Other"},
    "DA_POSITION": {"DEVELOPMENT_AGENT": "Development Agent", "SENIOR_DA": "Senior DA"},
}

GEO = {
    "hierarchy": [
        {"level": l, "level_id": f"level-{l}", "level_mnemonic": l,
         "level_value_id": f"{l}-1", "level_value_mnemonic": name}
        for l, name in (("region", "Tigray"), ("zone", "North Western"), ("woreda", "Tahtay Adiyabo"),
                        ("kebele", "Adi Hageray"))
    ],
    "lowest_level_value_id": "kebele-ET010101101001",
}

MESSAGE = {
    "reference_id": "FR-DA-0001", "source": "WEB_INTAKE", "approved_by": "Dr. Tewodros M.",
    "da": {
        "salutation": "Dr", "first_name": "Frehiwot", "father_name": "Assefa", "grandfather_name": "Bekele",
        "fayda_id": "8045 1234 5601", "gender": "Female", "marital_status": "Married",
        "birth_month_ec": 6, "birth_year_ec": 1986, "phone_number": "911556677",
        "email": "Frehiwot@Example.org", "education_level": "Masters", "specialisation": "Agronomy",
        "position": "Senior DA", "joining_date": "2017-09-11", "kebele_id": "kebele-ET010101101001",
        "not_a_field": "ignored",
    },
}


class TestDAServicesEnricher(unittest.TestCase):
    def setUp(self):
        rf.set_sections_for_tests(rf.DA_REGISTER_ID, [])  # the register metadata has no requirement here
        self.addCleanup(rf.set_sections_for_tests, rf.DA_REGISTER_ID, None)
        self.lists = mock.patch.object(module.code_lists, "field_attributes", return_value=(FIELD_ATTRIBUTES, FIELD_LABELS)); self.lists.start(); self.addCleanup(self.lists.stop)
        self.values = mock.patch.object(module.code_lists, "attribute_values", side_effect=lambda a: LISTS[a]); self.values.start(); self.addCleanup(self.values.stop)
        by_id = mock.patch.object(module._MasterDataGeo, "resolve_by_id", return_value=GEO)
        by_name = mock.patch.object(module._MasterDataGeo, "resolve", return_value=GEO)
        self.resolve_by_id, self.resolve = by_id.start(), by_name.start()
        self.addCleanup(by_id.stop)
        self.addCleanup(by_name.stop)
        self.enrich = module.DAServicesEnricherService().enrich

    def test_message_becomes_da_fields(self):
        out = self.enrich(MESSAGE, session=None)
        self.assertEqual((out["prefix"], out["first_name"], out["middle_name"], out["last_name"]),
                         ("DR", "Frehiwot", "Assefa", "Bekele"))
        self.assertEqual(out["foundational_id"], "804512345601")
        self.assertEqual((out["gender"], out["marital_status"]), ("FEMALE", "MARRIED"))
        self.assertEqual((out["birth_month_ec"], out["birth_year_ec"]), (6, 1986))
        self.assertEqual(out["mobile_number"], "0911556677")
        self.assertEqual(out["email"], "frehiwot@example.org")
        self.assertEqual((out["education_level"], out["position"]), ("MASTERS", "SENIOR_DA"))
        self.assertEqual(out["joined_date"], "2017-09-11")
        self.assertEqual(out["source"], "WEB_INTAKE")
        self.assertEqual((out["upstream_reference"], out["upstream_approved_by"]), ("FR-DA-0001", "Dr. Tewodros M."))
        self.assertEqual((out["kebele_name"], out["geo_lowest_level_value_id"]), ("Adi Hageray", "kebele-ET010101101001"))
        self.resolve_by_id.assert_called_once_with("kebele-ET010101101001")
        self.resolve.assert_not_called()

    def test_location_by_names_when_no_kebele_id(self):
        da = {k: v for k, v in MESSAGE["da"].items() if k != "kebele_id"}
        da.update(region="Tigray", zone="North Western", woreda="Tahtay Adiyabo", kebele="Adi Hageray")
        self.enrich(dict(MESSAGE, da=da), session=None)
        self.resolve.assert_called_once()

    def test_source_defaults_to_web_intake(self):
        msg = {k: v for k, v in MESSAGE.items() if k != "source"}
        self.assertEqual(self.enrich(msg, session=None)["source"], "WEB_INTAKE")

    def test_rejections(self):
        cases = [
            ({k: v for k, v in MESSAGE.items() if k != "reference_id"}, "Missing: reference_id"),
            (dict(MESSAGE, source="SMS"), "source 'SMS' is not one of"),
            (dict(MESSAGE, da={"first_name": "A"}), "Missing: father_name, fayda_id, kebele_id"),
            (dict(MESSAGE, da="not an object"), "message.da must be an object"),
        ]
        for message, text in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, text):
                    self.enrich(message, session=None)


if __name__ == "__main__":
    unittest.main()
