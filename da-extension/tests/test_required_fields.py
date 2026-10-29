"""Required fields come from the register metadata (widget-required), and the
intake guard checks them on save (new records) and finalize (whole submission).
Pure-Python parts run anywhere; the guard tests need the platform (container)."""

import importlib
import sys
import unittest
from unittest import mock

from openg2p_registry_da_extension.register_domain.services import required_fields as rf

REG = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
SCHEMA = {"panels": [{"widgets": [
    {"widget": "input", "widget-id": "first_name", "widget-label": "Name", "widget-required": True,
     "widget-data-path": f"{REG}.first_name"},
    {"widget": "input", "widget-id": "last_name", "widget-label": "Grandfather Name", "widget-required": False,
     "widget-data-path": f"{REG}.last_name"},
    {"widget": "input", "widget-id": "da_id", "widget-label": "DA-ID", "widget-required": True, "widget-readonly": True,
     "widget-data-path": f"{REG}.functional_record_id"},
    {"widget": "geo-hierarchy", "widget-id": "geo", "widget-label": "Region / Zone / Woreda / Kebele", "widget-required": True,
     "widget-data-path": {"value": f"{REG}.geo_lowest_level_value_id", "hierarchy": f"{REG}.geo_code_hierarchy_json"}},
]}]}


class TestSchema(unittest.TestCase):
    def test_required_fields_and_labels_from_metadata(self):
        self.assertEqual(rf.required_fields_in_schema(SCHEMA), {
            "first_name": "Name",
            "geo_lowest_level_value_id": "Region / Zone / Woreda / Kebele",
            "geo_code_hierarchy_json": "Region / Zone / Woreda / Kebele",
        })  # optional and read-only widgets are not required

    def test_fields_in_schema(self):
        self.assertEqual(rf.fields_in_schema(SCHEMA),
                         ["first_name", "last_name", "functional_record_id", "geo_lowest_level_value_id", "geo_code_hierarchy_json"])

    def test_missing_labels(self):
        required = rf.required_fields_in_schema(SCHEMA)
        self.assertEqual(rf.missing_labels(required, {"first_name": ""}, absent_is_missing=False), ["Name"])
        self.assertEqual(rf.missing_labels(required, {"first_name": "Abebe"}, absent_is_missing=False), [])
        self.assertEqual(rf.missing_labels(required, {"first_name": "Abebe"}, absent_is_missing=True),
                         ["Region / Zone / Woreda / Kebele"])
        self.assertEqual(rf.missing_labels(required, {}, absent_is_missing=True), ["Name", "Region / Zone / Woreda / Kebele"])


class TestGuard(unittest.IsolatedAsyncioTestCase):
    """The subclass refuses an empty new section and an incomplete finalize,
    and hands complete ones to the platform."""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
        try:
            cls.guard = importlib.import_module("openg2p_registry_da_extension.register_domain.services.da_intake_guard")
        except Exception as exc:  # platform not importable on this host
            raise unittest.SkipTest(f"platform not importable: {exc}")

    def _service(self):
        svc = self.guard.DAIntakeFormDataService.__new__(self.guard.DAIntakeFormDataService)
        section = mock.Mock(section_ui_schema=SCHEMA, section_id="s1", is_list=False, section_description="DA details")
        svc._get_section_or_error = mock.AsyncMock(return_value=section)
        svc._records_for_validation = staticmethod(lambda records: [r for r in (records or []) if (r or {}).get("edit_action") != "DELETE"])
        svc._get_submission_or_error = mock.AsyncMock(return_value=mock.Mock(form_id="f1", submission_id="sub"))
        svc._get_form_sections = mock.AsyncMock(return_value=[section])
        svc._resolve_intake_form_class = mock.AsyncMock(return_value=object)
        svc._get_intake_rows = mock.AsyncMock(return_value={"rec-1": mock.Mock(internal_record_id="rec-1")})
        return svc

    async def test_save_new_record_without_required_fields_is_refused(self):
        from openg2p_registry_core.errors import G2PRegistryException
        svc = self._service()
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")) as sup:
            with self.assertRaises(G2PRegistryException) as ctx:
                await svc.save_intake_form_submission_with_session(None, "s1", [{"edit_action": "ADD"}], REG, "f1", REG, "u", None)
            self.assertIn("Required: DA details: fill in Name, Region / Zone / Woreda / Kebele", str(ctx.exception))
            sup.assert_not_called()

    async def test_save_complete_record_and_partial_update_pass_through(self):
        svc = self._service()
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")) as sup:
            full = {"edit_action": "ADD", "first_name": "Abebe", "geo_lowest_level_value_id": "k1", "geo_code_hierarchy_json": {"hierarchy": []}}
            self.assertEqual(await svc.save_intake_form_submission_with_session(None, "s1", [full], REG, "f1", REG, "u", None), "saved")
            self.assertEqual(await svc.save_intake_form_submission_with_session("sub", "s1", [{"edit_action": "UPDATE", "internal_record_id": "rec-1", "last_name": "X"}], REG, "f1", REG, "u", None), "saved")
            self.assertEqual(sup.await_count, 2)

    async def test_update_on_a_record_the_submission_does_not_hold_is_a_new_record(self):
        from openg2p_registry_core.errors import G2PRegistryException
        svc = self._service()
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")) as sup:
            for sid, rec in ((None, {"edit_action": "UPDATE", "internal_record_id": "", "first_name": "Abebe"}),
                             ("sub", {"edit_action": "UPDATE", "internal_record_id": "rec-9", "first_name": "Abebe"})):
                with self.assertRaises(G2PRegistryException) as ctx:
                    await svc.save_intake_form_submission_with_session(sid, "s1", [rec], REG, "f1", REG, "u", None)
                self.assertIn("Required: DA details: fill in Region / Zone / Woreda / Kebele", str(ctx.exception))
            sup.assert_not_called()

    async def test_import_records_are_not_checked(self):
        svc = self._service()
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "save_intake_form_submission_with_session", new=mock.AsyncMock(return_value="saved")):
            self.assertEqual(await svc.save_intake_form_submission_with_session(None, "s1", [{"edit_action": "ADD", "source": "CSV_IMPORT"}], REG, "f1", REG, "u", None), "saved")

    async def test_finalize_incomplete_submission_is_refused(self):
        from openg2p_registry_core.errors import G2PRegistryException
        svc = self._service()
        payload = mock.Mock(section_id="s1", records=[{"first_name": "Abebe"}])
        svc._build_section_payloads = mock.AsyncMock(return_value=[payload])
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "finalize_submission_with_session", new=mock.AsyncMock(return_value="final")) as sup:
            with self.assertRaises(G2PRegistryException) as ctx:
                await svc.finalize_submission_with_session("sub", None)
            self.assertIn("Cannot submit for approval. Required: DA details: fill in Region / Zone / Woreda / Kebele", str(ctx.exception))
            sup.assert_not_called()
            svc._build_section_payloads = mock.AsyncMock(return_value=[])  # no section saved at all
            with self.assertRaises(G2PRegistryException) as ctx:
                await svc.finalize_submission_with_session("sub", None)
            self.assertIn("fill in Name, Region / Zone / Woreda / Kebele", str(ctx.exception))

    async def test_finalize_complete_submission_passes_through(self):
        svc = self._service()
        payload = mock.Mock(section_id="s1", records=[{"first_name": "Abebe", "geo_lowest_level_value_id": "k1", "geo_code_hierarchy_json": {"hierarchy": [1]}}])
        svc._build_section_payloads = mock.AsyncMock(return_value=[payload])
        with mock.patch.object(self.guard.G2PIntakeFormDataService, "finalize_submission_with_session", new=mock.AsyncMock(return_value="final")) as sup:
            self.assertEqual(await svc.finalize_submission_with_session("sub", None), "final")
            sup.assert_awaited_once()

    def test_install_puts_the_guard_first(self):
        from openg2p_fastapi_common.context import component_registry
        from openg2p_registry_core.services.intake_form_data_service import G2PIntakeFormDataService
        platform = G2PIntakeFormDataService()
        try:
            guard = self.guard.install_da_intake_guard()
            self.assertIs(G2PIntakeFormDataService.get_component(), guard)
            self.assertIs(self.guard.install_da_intake_guard(), guard)  # idempotent
        finally:
            for c in [c for c in component_registry if isinstance(c, G2PIntakeFormDataService)]:
                component_registry.remove(c)


if __name__ == "__main__":
    unittest.main()
