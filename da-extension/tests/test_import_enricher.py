"""DAImportFileEnricherService: one CSV / XLSX row -> DA fields.

The Master Data lookup is replaced with a stub; the rest runs as in the worker.
Imports openg2p_registry_core, so it runs in the container.
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
        for l, name in (("region", "Amhara"), ("zone", "Awi"), ("woreda", "Banja"), ("kebele", "Barie"))
    ],
    "lowest_level_value_id": "kebele-1",
}

ROW = {
    "Salutation": "Mr.", " Name *": "Abebe", "Father's Name": "Kebede", "Grandfather Name": "",
    "Fayda ID": "412345678901.0", "Sex": "Male", "Marital Status": "married",
    "Month of Birth (EC)": "4.0", "Year of Birth (EC)": "1985", "Phone Number": "911234567",
    "Telegram": "", "Alternate Number": "+251 922 334 455", "Email": "ABEBE@EXAMPLE.ORG",
    "Education Level": "degree", "Specialization": "crop production", "Position": "Senior DA",
    "Joining Date": "2015-09-11 00:00:00", "Region": "amhara", "Zone": "Awi", "Woreda": "Banja",
    "Kebele": "Barie", "Unknown column": "ignored",
}


class TestEnricher(unittest.TestCase):
    def setUp(self):
        rf.set_sections_for_tests(rf.DA_REGISTER_ID, [])  # the register metadata has no requirement here
        self.addCleanup(rf.set_sections_for_tests, rf.DA_REGISTER_ID, None)
        patcher = mock.patch.object(module._MasterDataGeo, "resolve", return_value=GEO)
        self.lists = mock.patch.object(module.code_lists, "field_attributes", return_value=(FIELD_ATTRIBUTES, FIELD_LABELS)); self.lists.start(); self.addCleanup(self.lists.stop)
        self.values = mock.patch.object(module.code_lists, "attribute_values", side_effect=lambda a: LISTS[a]); self.values.start(); self.addCleanup(self.values.stop)
        self.resolve = patcher.start()
        self.addCleanup(patcher.stop)
        self.enrich = module.DAImportFileEnricherService().enrich

    def test_row_becomes_da_fields(self):
        out = self.enrich(dict(ROW), session=None)
        self.assertEqual(out["prefix"], "MR")
        self.assertEqual((out["first_name"], out["middle_name"], out["last_name"]), ("Abebe", "Kebede", None))
        self.assertEqual(out["foundational_id"], "412345678901")
        self.assertEqual((out["gender"], out["marital_status"]), ("MALE", "MARRIED"))
        self.assertEqual((out["birth_month_ec"], out["birth_year_ec"]), (4, 1985))
        self.assertEqual(out["mobile_number"], "0911234567")  # leading 0 restored
        self.assertIsNone(out["telegram_number"])
        self.assertEqual(out["alternate_number"], "+251922334455")
        self.assertEqual(out["email"], "abebe@example.org")
        self.assertEqual(out["education_level"], "DEGREE")
        self.assertEqual(out["specialisation"], "CROP_PRODUCTION")
        self.assertEqual(out["position"], "SENIOR_DA")
        self.assertEqual(out["joined_date"], "2015-09-11")
        self.assertEqual(out["source"], "CSV_IMPORT")
        self.assertEqual(out["geo_lowest_level_value_id"], "kebele-1")
        self.assertEqual((out["region_name"], out["kebele_name"]), ("Amhara", "Barie"))
        self.resolve.assert_called_once_with(
            {"region": "amhara", "zone": "Awi", "woreda": "Banja", "kebele": "Barie"})

    def test_missing_identity_or_location_is_rejected(self):
        row = dict(ROW, **{"Fayda ID": "", "Kebele": ""})
        with self.assertRaisesRegex(ValueError, "Missing: Fayda ID, Kebele"):
            self.enrich(row, session=None)

    def test_unknown_code_lists_the_allowed_values(self):
        with self.assertRaisesRegex(ValueError, "Position 'Manager' is not one of: Development Agent, Senior DA"):
            self.enrich(dict(ROW, Position="Manager"), session=None)

    def test_bad_date_and_number(self):
        with self.assertRaisesRegex(ValueError, "Joining Date '2015/31/31' must be a date"):
            self.enrich(dict(ROW, **{"Joining Date": "2015/31/31"}), session=None)
        with self.assertRaisesRegex(ValueError, "Year of Birth \\(EC\\) 'nineteen' must be a whole number"):
            self.enrich(dict(ROW, **{"Year of Birth (EC)": "nineteen"}), session=None)


if __name__ == "__main__":
    unittest.main()
