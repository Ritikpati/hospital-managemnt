# hospital-management - deployment

Push to GitHub -> **terraform-infra** (S3 backend, VPC, EKS, 3x RDS PostgreSQL + 3 read replicas, S3, SNS, IAM)
-> **build-scan-push-ecr** (ECR repos, build, Trivy, push, update manifests) -> **deploy** job (ArgoCD + app, prints URL).

## GitHub secrets (Settings -> Secrets and variables -> Actions)
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DB_USERNAME` (e.g. `hmsadmin`, not `admin`), `DB_PASSWORD` (>=12 chars, no `/ @ " '` or spaces),
`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `JWT_SECRET`; optional `GH_USERNAME`.
Optional: `TFVARS` = the full contents of your local `terraform/terraform.tfvars` (without db_username / db_password, those come from the secrets above).
Also: Settings -> Actions -> General -> Workflow permissions -> **Read and write**.

## Databases
RDS PostgreSQL 16: `hms-authdb`, `hms-patientdb`, `hms-billingdb`, each with `<name>-replica`.
Primary = writes, replica = reads. Endpoints are discovered automatically by the deploy job and injected as
secrets `authdb-conn`, `patientdb-conn`, `billingdb-conn`; nothing to edit by hand.

## Run
Push to `main`. Open the run summary of **build-scan-push-ecr -> deploy** to get the APPLICATION URL.
(RDS creation takes ~15-25 minutes; the deploy job waits for it.)

## Terraform variables
All tunables live in `terraform/variables.tf`. Your values go in `terraform/terraform.tfvars` (gitignored).
Start from `cp terraform/terraform.tfvars.example terraform/terraform.tfvars`. Locally: `terraform plan` picks it up automatically.
In CI the file is not in git, so paste its contents (minus the db credentials) into the `TFVARS` GitHub secret; if unset, the defaults apply.
Keep `region`, `project` and `cluster_name` at `us-east-1` / `hms` / `hms-eks` unless you also update `docker-build.yml` and `k8s/*.yaml`, which still hardcode them.
