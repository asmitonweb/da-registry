"""Required fields on every channel: widget-required (with its show / hide /
require conditions) is refused on save ("Next") for the web form, and on submit
for the web form, file imports and partner pushes, with a readable reason.

The condition evaluator and the problem phrases are pure Python; the intake
service and the enrichers need the platform, so they run in the container.
"""

import importlib
import sys
import unittest
from unittest import mock

from openg2p_registry_da_extension.register_domain.services import required_fields as rf
from openg2p_registry_da_extension.register_domain.services.push_status import exception_type

REG = rf.DA_REGISTER_ID


def widget(field, label, required=True, options=None):
    out = {"widget": "input", "widget-label": label, "widget-required": required,
           "widget-data-path": f"{REG}.{field}"}
    if options:
        out["widget-data-options"] = options
    return out


def schema(*widgets):
    return {"panels": [{"widgets": list(widgets)}]}


CONTACT = schema(widget("mobile_number", "Mobile Number"), widget("email", "Email"), widget("telegram_number", "Telegram", False))
HIDE_WHEN_NO_PHONE = {"actions": [{"action": "hide", "condition": {"field": f"{REG}.has_phone", "operator": "equals", "value": False}}]}
CONDITIONAL = schema(
    widget("has_phone", "Has Phone", False),
    widget("mobile_number", "Mobile Number", True, HIDE_WHEN_NO_PHONE),
    widget("reason", "Reason", False, {"actions": [
        {"action": "require", "condition": {"field": f"{REG}.has_phone", "operator": "equals", "value": False}}]}),
)
TABLE = schema({
    "widget": "dialog-table", "widget-label": "Training Courses", "widget-required": True,
    "widget-data-path": f"{REG}.courses",
    "widget-data-columns": [
        {"column-key": "title", "column-label": "Course Title", "widget-required": True},
        {"column-key": "year", "column-label": "Year", "widget-required": False},
    ],
})


class TestConditions(unittest.TestCase):
    def test_operators(self):
        record = {"species": "GOAT", "tags": ["a", "b"], "blank": " "}
        cases = [
            ({"field": "r.species", "operator": "equals", "value": "GOAT"}, True),
            ({"field": "r.species", "operator": "notEquals", "value": "GOAT"}, False),
            ({"field": "r.species", "operator": "in", "value": ["GOAT", "SHEEP"]}, True),
            ({"field": "r.species", "operator": "notIn", "value": ["GOAT"]}, False),
            ({"field": "r.blank", "operator": "empty"}, True),
            ({"field": "r.species", "operator": "notEmpty"}, True),
            ({"field": "r.tags", "operator": "contains", "value": "b"}, True),
            ({"and": [{"field": "species", "operator": "equals", "value": "GOAT"},
                      {"field": "blank", "operator": "empty"}]}, True),
            ({"or": [{"field": "species", "operator": "equals", "value": "COW"},
                     {"field": "species", "operator": "equals", "value": "GOAT"}]}, True),
            ({"not": {"field": "species", "operator": "equals", "value": "GOAT"}}, False),
            ({"field": "species", "operator": "someFutureOperator"}, None),
        ]
        for condition, expected in cases:
            with self.subTest(condition=condition):
                self.assertIs(rf.evaluate_condition(condition, record), expected)

    def test_hidden_field_is_not_required(self):
        self.assertEqual(rf.problems(CONDITIONAL, {"has_phone": False, "reason": "x"}, absent_is_missing=True), [])
        self.assertEqual(rf.problems(CONDITIONAL, {"has_phone": True, "reason": ""}, absent_is_missing=True),
                         ["fill in Mobile Number"])

    def test_require_action_makes_a_field_required(self):
        self.assertEqual(rf.problems(CONDITIONAL, {"has_phone": False, "reason": ""}, absent_is_missing=True),
                         ["fill in Reason"])

    def test_show_action(self):
        options = {"actions": [{"action": "show", "condition": {"field": "kind", "operator": "equals", "value": "A"}}]}
        only_a = schema(widget("extra", "Extra", True, options))
        self.assertEqual(rf.problems(only_a, {"kind": "B"}, absent_is_missing=True), [])
        self.assertEqual(rf.problems(only_a, {"kind": "A"}, absent_is_missing=True), ["fill in Extra"])


class TestPhrases(unittest.TestCase):
    def test_readable_without_codes_or_underscores(self):
        phrases = rf.problems(schema(widget("alternate_number", "")), {}, absent_is_missing=True)
        self.assertEqual(phrases, ["fill in Alternate Number"])
        self.assertEqual(rf.describe("Contact", rf.problems(CONTACT, {}, absent_is_missing=True)),
                         "Contact: fill in Mobile Number, Email")

    def test_table_with_zero_rows_and_row_columns(self):
        self.assertEqual(rf.problems(TABLE, {"courses": []}, absent_is_missing=True), ["add at least one Training Courses row"])
        self.assertEqual(rf.problems(TABLE, {}, absent_is_missing=True), ["add at least one Training Courses row"])
        self.assertEqual(rf.problems(TABLE, {"courses": [{"title": "A"}, {"year": 2020}]}, absent_is_missing=True),
                         ["Training Courses row 2: fill in Course Title"])
        self.assertEqual(rf.problems(TABLE, {"courses": [{"title": "A"}]}, absent_is_missing=True), [])
        self.assertEqual(rf.problems(TABLE, {"other": 1}, absent_is_missing=False), [])  # partial update


class TestIntakeService(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
        try:
            cls.guard = importlib.import_module("openg2p_registry_da_extension.register_domain.services.da_intake_guard")
            cls.errors = importlib.import_module("openg2p_registry_core.errors")
        except Exception as exc:  # platform not importable on this host
            raise unittest.SkipTest(f"platform not importable: {exc}")

    def service(self, sections, payloads=None, stored=None):
        svc = self.guard.DAIntakeFormDataService.__new__(self.guard.DAIntakeFormDataService)
        by_id = {s.section_id: s for s in sections}
        svc._get_section_or_error = mock.AsyncMock(side_effect=lambda section_id, session: by_id[section_id])
        svc._records_for_validation = staticmethod(lambda r: [x for x in (r or []) if (x or {}).get("edit_action") != "DELETE"])
        svc._get_submission_or_error = mock.AsyncMock(return_value=mock.Mock(form_id="f1", submission_id="sub"))
        svc._get_form_sections = mock.AsyncMock(return_value=sections)
        svc._resolve_intake_form_class = mock.AsyncMock(return_value=object)
        svc._get_intake_rows = mock.AsyncMock(return_value=stored or {})
        svc._build_section_payloads = mock.AsyncMock(return_value=payloads or [])
        return svc

    @staticmethod
    def section(section_id, ui, name, is_list=False):
        return mock.Mock(section_id=section_id, section_ui_schema=ui, section_description=name, is_list=is_list)

    def test_one_service_with_the_mixin(self):
        mixin = importlib.import_module("openg2p_registry_da_extension.register_domain.services.required_fields_mixin")
        names = [c.__name__ for c in self.guard.DAIntakeFormDataService.__mro__[:4]]
        self.assertEqual(names, ["DAIntakeFormDataService", "RequiredFieldsMixin", "DirectApprovalClosed",
                                 "G2PIntakeFormDataService"])
        self.assertIs(self.guard.DAIntakeFormDataService.__mro__[1], mixin.RequiredFieldsMixin)

    async def test_save_empty_section_is_refused_and_complete_passes(self):
        svc = self.service([self.section("c", CONTACT, "Contact")])
        parent = self.guard.G2PIntakeFormDataService
        with mock.patch.object(parent, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")) as sup:
            with self.assertRaises(self.errors.G2PRegistryException) as ctx:
                await svc.save_intake_form_submission_with_session(None, "c", [{"edit_action": "ADD"}], REG, "f1", REG, "u", None)
            self.assertIn("Required: Contact: fill in Mobile Number, Email", str(ctx.exception))
            sup.assert_not_called()
            ok = {"edit_action": "ADD", "mobile_number": "0911223344", "email": "a@b.org"}
            self.assertEqual(await svc.save_intake_form_submission_with_session(None, "c", [ok], REG, "f1", REG, "u", None), "saved")

    async def test_save_hidden_field_is_not_required(self):
        svc = self.service([self.section("c", CONDITIONAL, "Contact")])
        parent = self.guard.G2PIntakeFormDataService
        with mock.patch.object(parent, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")):
            record = {"edit_action": "ADD", "has_phone": False, "reason": "No phone"}
            self.assertEqual(await svc.save_intake_form_submission_with_session(None, "c", [record], REG, "f1", REG, "u", None), "saved")

    async def test_save_list_section_with_no_rows_is_refused(self):
        svc = self.service([self.section("t", TABLE, "Training", is_list=True)])
        parent = self.guard.G2PIntakeFormDataService
        with mock.patch.object(parent, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")) as sup:
            with self.assertRaises(self.errors.G2PRegistryException) as ctx:
                await svc.save_intake_form_submission_with_session("sub", "t", [], REG, "f1", REG, "u", None)
            self.assertIn("Training: add at least one row", str(ctx.exception))
            sup.assert_not_called()

    async def test_finalize_incomplete_is_refused_for_every_source(self):
        svc = self.service([self.section("c", CONTACT, "Contact"), self.section("t", TABLE, "Training", is_list=True)])
        parent = self.guard.G2PIntakeFormDataService
        for source in ("WEB_INTAKE", "CSV_IMPORT", "DA_SERVICES"):
            with self.subTest(source=source):
                svc._build_section_payloads = mock.AsyncMock(return_value=[
                    mock.Mock(section_id="c", records=[{"source": source, "email": "a@b.org"}]),
                    mock.Mock(section_id="t", records=[{"source": source, "title": ""}]),
                ])
                with mock.patch.object(parent, "finalize_submission_with_session", new=mock.AsyncMock(return_value="final")) as sup:
                    with self.assertRaises(self.errors.G2PRegistryException) as ctx:
                        await svc.finalize_submission_with_session("sub", None)
                    message = str(ctx.exception)
                    self.assertIn("Cannot submit for approval. Required: Contact: fill in Mobile Number", message)
                    sup.assert_not_called()

    async def test_finalize_list_section_with_zero_rows_is_refused(self):
        svc = self.service([self.section("t", TABLE, "Training", is_list=True)], payloads=[])
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "finalize_submission_with_session", new=mock.AsyncMock(return_value="final")):
            with self.assertRaises(self.errors.G2PRegistryException) as ctx:
                await svc.finalize_submission_with_session("sub", None)
            self.assertIn("Training: add at least one row", str(ctx.exception))

    async def test_finalize_complete_submission_passes_for_an_import(self):
        svc = self.service([self.section("c", CONTACT, "Contact")], payloads=[
            mock.Mock(section_id="c", records=[{"source": "CSV_IMPORT", "mobile_number": "0911223344", "email": "a@b.org"}])])
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "finalize_submission_with_session", new=mock.AsyncMock(return_value="final")):
            self.assertEqual(await svc.finalize_submission_with_session("sub", None), "final")


class TestImportsAndPartnerPushes(unittest.TestCase):
    """The enrichers refuse an incomplete record with a ValueError (the worker
    records it against the row and carries on); the exceptions list shows it as
    a missing mandatory field with the readable reason."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.module = importlib.import_module(
                "openg2p_registry_da_extension.ingestion_pipeline.enricher_services.g2p_da_enricher_services")
        except Exception as exc:  # platform not importable on this host
            raise unittest.SkipTest(f"platform not importable: {exc}")

    def setUp(self):
        self.sections = [("DA contact details", CONTACT, False)]
        rf.set_sections_for_tests(REG, self.sections)
        self.addCleanup(rf.set_sections_for_tests, REG, None)

    def test_complete_record_passes(self):
        self.module._require_complete({"mobile_number": "0911223344", "email": "a@b.org"}, session=None)

    def test_incomplete_record_is_refused_with_a_readable_reason(self):
        with self.assertRaises(ValueError) as ctx:
            self.module._require_complete({"mobile_number": "0911223344", "email": None}, session=None)
        reason = str(ctx.exception)
        self.assertEqual(reason, "Required: DA contact details: fill in Email")
        self.assertEqual(exception_type(reason), "MISSING_MANDATORY_FIELD")

    def test_import_and_partner_enrichers_run_the_check(self):
        geo = {"hierarchy": [{"level_mnemonic": "kebele", "level_value_mnemonic": "Barie"}], "lowest_level_value_id": "k1"}
        base = {"first_name": "Abebe", "middle_name": "Kebede", "foundational_id": "4123456789012345"}
        with mock.patch.object(self.module._MasterDataGeo, "resolve", return_value=geo), \
                mock.patch.object(self.module._MasterDataGeo, "resolve_by_id", return_value=geo), \
                mock.patch.object(self.module.code_lists, "resolve_code", return_value=None):
            row = {"Name": "Abebe", "Father Name": "Kebede", "Fayda ID": "4123456789012345",
                   "Region": "r", "Zone": "z", "Woreda": "w", "Kebele": "k"}
            with self.assertRaises(ValueError) as ctx:
                self.module.DAImportFileEnricherService().enrich(row, session=None)
            self.assertIn("Required: DA contact details: fill in Mobile Number, Email", str(ctx.exception))
            message = {"reference_id": "FR-1", "source": "WEB_INTAKE",
                       "da": {"first_name": base["first_name"], "father_name": base["middle_name"],
                              "fayda_id": base["foundational_id"], "kebele_id": "k1"}}
            with self.assertRaises(ValueError) as ctx:
                self.module.DAServicesEnricherService().enrich(message, session=None)
            self.assertIn("Required: DA contact details: fill in Mobile Number, Email", str(ctx.exception))
            message["da"].update(phone_number="911223344", email="a@b.org")
            out = self.module.DAServicesEnricherService().enrich(message, session=None)
            self.assertEqual(out["email"], "a@b.org")


if __name__ == "__main__":
    unittest.main()
