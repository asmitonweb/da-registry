# Follow-ups to fix or review later

Open items found while bringing the DA registry in line with the OpenG2P standards (29 October 2026). None of them blocks building and pushing the images; the dev deploy stays off (`DEPLOY_TO_DEV`, default false) until the deployment items are done.

## Deployment (before turning the dev deploy on)

| Item | What is wrong | What to do |
|---|---|---|
| Release target | The Jenkinsfile upgrades release `da` in namespace `commons`, which has no workloads. The DA that runs is release `da-registry` in namespace `da-registry`. | Settle the one release and namespace; point the pipeline at it. |
| Chart and platform pin | `HELM_CHART_VERSION` 1.0.0-dev.5 brings registry-platform rc.544, the images are rc.557. | Move the chart and the images to the same platform version together. |
| Values | The pipeline upgrades with `--reuse-values`, values live in this repository (`deploy/dev/values-da.yaml`), and the repository keeps its own chart copy (`helm/openg2p-da-registry`). Crop Sown and Livestock pin their values in oan-helm (`ci/deploy/oan-chart.json`). | Port to the Crop Sown and Livestock pattern: pinned values in oan-helm, `--reset-values`, no chart copy here. |
| Keycloak client | `da-registry-backend` (service account) and its secret `da-registry-backend-keycloak` / `client-secret` do not exist on the dev cluster. The references are optional, so the pods start; imports and DA Services pushes cannot open an approval until it exists. | Create the client and the secret (Keycloak admin). |
| DA Services service account | DA Services serves a DA their own profile through a service account (`docs/rbac-registry-roles.md` §5). | Create a confidential client with service accounts in realm `staff` and give its service-account user the client role Data Editor on `da-registry-staff-portal`; hand the secret to DA Services. |
| Master Data lists | The form's dropdowns read `DA_EDUCATION_LEVEL`, `DA_SPECIALISATION`, `DA_POSITION`, `DA_SOURCE`. | Merge openg2p-data PR 22 and re-run the Master Data seed (`PACK_DOMAINS=agriculture`). |

## Sample data (decision of 29 October 2026) - done

`docker/db-seed/load_sample_data.py` again, run by the platform entrypoint only when `loadSampleData=true`, with the COSS openg2p-data fork baked into the db-seed image at a pinned commit (`OPENG2P_DATA_REF`). It submits each sample DA through the intake API (four section saves and finalize) with the registry client's service account, the settings the platform chart's db-seed job already sets (`STAFF_*`, `MDS_*`); it never signs in as an approver and never approves, so sample records wait for the approvers. A DA whose Fayda ID is already registered or in a live submission is skipped. The entrypoint seeds the AWE policies after the sample step, so the loader applies the same idempotent AWE seed files first. The client's service-account user needs the client role Intake Officer on the staff portal client. `load_codelists_mdm.py` stays local-only (`docker/local-dev/data-loaders`).

## Code to review

| Item | Note |
|---|---|
| Temporary platform overrides | One override kept by decision until OpenG2P fixes the platform, in `register_domain/temporary_platform_overrides.py`: IAM permissions per application (IAM 1.4.2 still looks a role up by name only). Raise each with OpenG2P and remove it once fixed; re-check on every platform upgrade (`docs/refactor/platform-overrides.md`). |
| Full-stack check | The service-token approval start for imports and the direct-approval refusal are covered by unit tests only. Run them once on a stack with Keycloak, the approval workflow engine and Postgres. |
| Package name | `openg2p_registry_da_extension` matches the OpenG2P docs. Spelling out `development_agent` would change the package, release, namespace and database; a candidate for a naming window only. |
