# Follow-ups to fix or review later

Open items found while bringing the DA registry in line with the OpenG2P standards (29 October 2026). None of them blocks building and pushing the images; the dev deploy stays off (`DEPLOY_TO_DEV`, default false) until the deployment items are done.

## Deployment (before turning the dev deploy on)

| Item | What is wrong | What to do |
|---|---|---|
| Release target | The Jenkinsfile upgrades release `da` in namespace `commons`, which has no workloads. The DA that runs is release `da-registry` in namespace `da-registry`. | Settle the one release and namespace; point the pipeline at it. |
| Chart and platform pin | `HELM_CHART_VERSION` 1.0.0-dev.5 brings registry-platform rc.544, the images are rc.557. | Move the chart and the images to the same platform version together. |
| Values | The pipeline upgrades with `--reuse-values`, values live in this repository (`deploy/dev/values-da.yaml`), and the repository keeps its own chart copy (`helm/openg2p-da-registry`). Crop Sown and Livestock pin their values in oan-helm (`ci/deploy/oan-chart.json`). | Port to the Crop Sown and Livestock pattern: pinned values in oan-helm, `--reset-values`, no chart copy here. |
| Keycloak client | `da-registry-backend` (service account) and its secret `da-registry-backend-keycloak` / `client-secret` do not exist on the dev cluster. The references are optional, so the pods start; imports and DA Services pushes cannot open an approval until it exists. | Create the client and the secret (Keycloak admin). |
| Self-service scope | Scope `da-self-service` and attribute `da_id` in the `staff` realm are not created. | Create them before testing a Development Agent's own-record access. |
| Master Data lists | The form's dropdowns read `DA_EDUCATION_LEVEL`, `DA_SPECIALISATION`, `DA_POSITION`, `DA_SOURCE`. | Merge openg2p-data PR 22 and re-run the Master Data seed (`PACK_DOMAINS=agriculture`). |

## Sample data (decision of 29 October 2026)

The db-seed follows the OpenG2P standard exactly: the sample step is `docker/db-seed/load_sample_data.py`, run only when `loadSampleData=true`, and the data comes from our fork of openg2p-data at a pinned commit. A sample loader never approves records by signing in the demo approvers through Keycloak, never turns on direct access grants and never resets passwords; sample records wait for a person to approve them.

- The loader parked in `docs/refactor/moves-to-openg2p-data/` goes back to `docker/db-seed/load_sample_data.py`.
- It currently inserts DA records straight into the register tables. Rewrite it to submit through the intake API (as OpenG2P's reference loaders do) and leave approval to the approvers.
- `load_codelists_mdm.py` is local-only (the dev Master Data is seeded by its own db-seed); keep it out of the deployable image.

## Code to review

| Item | Note |
|---|---|
| Master Data read from its database | `code_lists.py` and the geo lookup read Master Data's Postgres when `REGISTRY_CELERY_WORKERS_MASTER_DATA_DB_*` is set. The standard is the Master Data API (`/attributes/get_attribute_values`, already supported here). Move the import path to the API and drop the database read mode. |
| Temporary platform overrides | Three overrides kept by decision until OpenG2P fixes the platform, in `register_domain/temporary_platform_overrides.py`: IAM permissions per application, worker database pool, a Development Agent seeing only their own record. Raise each with OpenG2P and remove it once fixed; re-check on every platform upgrade (`docs/refactor/platform-overrides.md`). |
| Full-stack check | The service-token approval start for imports and the direct-approval refusal are covered by unit tests only. Run them once on a stack with Keycloak, the approval workflow engine and Postgres. |
| Package name | `openg2p_registry_da_extension` matches the OpenG2P docs. Spelling out `development_agent` would change the package, release, namespace and database; a candidate for a naming window only. |
