# AWS Sandbox Migration — Demo Log

Project: Project Management Platform (FastAPI/PostgreSQL/S3/Lambda/JWT)
Goal: switch from LocalStack (local dev) to real AWS via EPAM/Syndicate Cloud Sandbox.
Constraints: region ∈ {us-east-1, eu-west-1, ap-south-1}; no "epam" in any resource name.

Chosen bucket name: `project-mgmt-docs-f4a8baae`
Chosen region: `us-east-1`

---

## Step 1 — Audit for hardcoded LocalStack coupling

Findings:
- `app/services/s3_service.py::get_s3_client()` calls `boto3.client("s3", region_name=..., aws_access_key_id=..., aws_secret_access_key=...)` — **no `endpoint_url` passed**.
- `lambda/file_size_calculator.py` calls `boto3.client("s3")` with no args at all.
- LocalStack connection was driven entirely by the `AWS_ENDPOINT_URL` env var, set only in `docker-compose.yml`'s `api.environment` block (boto3/botocore auto-honors this var) — never in `.env`, never in Python code.
- `tests/conftest.py` mocks S3 via `moto` (`mock_aws()`), not a real network call to LocalStack — so the test suite has zero LocalStack coupling to begin with.

Conclusion: config-only change was sufficient — no business logic touched.

## Step 2 — Config changes (local edits, no AWS calls)

- [.env](.env): removed implicit epam-named bucket, set `S3_BUCKET_NAME=project-mgmt-docs-f4a8baae`, added placeholders for real `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, region kept `us-east-1`.
- [.env.example](.env.example): same bucket-naming convention documented.
- [app/core/config.py](app/core/config.py): default `s3_bucket_name` fallback updated to `project-mgmt-docs-f4a8baae`.
- [docker-compose.yml](docker-compose.yml): removed the `localstack` service and the hardcoded `AWS_ACCESS_KEY_ID=test` / `AWS_ENDPOINT_URL=http://localstack:4566` overrides from the `api` service — base file now targets real AWS via `.env`.
- [docker-compose.localstack.yml](docker-compose.localstack.yml) (new): overlay file that restores the LocalStack service + env overrides for local dev, via:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.localstack.yml up --build
  ```

## Step 2b — Live Sandbox credentials obtained (new session)

A fresh Sandbox session was started and temporary STS credentials were shared and verified:

```
$ python3 -c "import boto3,json; print(json.dumps(boto3.client('sts').get_caller_identity(), indent=2))"
{
  "UserId": "AROA5JMSUHM2ACZFN2AXD:SandboxAccessSession-console",
  "Account": "913524931380",
  "Arn": "arn:aws:sts::913524931380:assumed-role/SandboxAccessRole-console/SandboxAccessSession-console"
}
```

Region: `us-east-1` (allowed). Credentials are temporary (`AWS_SESSION_TOKEN` present, key
prefix `ASIA`) and were kept out of the repo — stored only in a local scratch env file,
never committed.

## Step 3 — Create real S3 bucket

```
$ python3 - <<'PY'
s3.create_bucket(Bucket="project-mgmt-docs-f4a8baae")
s3.put_public_access_block(Bucket=..., PublicAccessBlockConfiguration={all True})
s3.put_bucket_encryption(Bucket=..., ... AES256 ...)
PY
create_bucket: 200
public access block: set
default encryption: set (AES256)
region: us-east-1 (LocationConstraint None == us-east-1, AWS quirk)
```

Bucket `project-mgmt-docs-f4a8baae` live in `us-east-1`, public access fully blocked,
default SSE-AES256 enabled. No "epam" anywhere in the name.

## Step 4 — Deploy Lambda + S3 event trigger

Sandbox SCP findings along the way (both are org-level explicit denies, not bugs):
- `rds:DescribeDBInstances` → **denied**. No RDS available in this sandbox, so the Lambda's
  Postgres UPDATE step cannot reach a real network-accessible DB here. Documented as a known
  sandbox limitation — production would run Lambda in the same VPC as an RDS instance.
- `kms:Encrypt` on the default Lambda env-var key → **denied**. Lambda's built-in
  "Environment variables" feature always encrypts via KMS, so it can't be used at all in this
  sandbox. Worked around with a deploy-only `bootstrap.py` shim that sets `os.environ` in
  Python before importing the unmodified `file_size_calculator.py` handler — no business
  logic touched, only how config reaches the process.

Steps executed:
```
iam.create_role("project-mgmt-lambda-role-f4a8baae", trust=lambda.amazonaws.com)
  -> arn:aws:iam::913524931380:role/project-mgmt-lambda-role-f4a8baae
iam.attach_role_policy(AWSLambdaBasicExecutionRole)
iam.put_role_policy(inline: s3:GetObject/ListBucket on project-mgmt-docs-f4a8baae)

# package: pip install --platform manylinux2014_x86_64 --python-version 3.12 psycopg2-binary
# zip: file_size_calculator.py (unmodified) + bootstrap.py (deploy shim) + psycopg2 wheel contents

lambda.create_function(
  FunctionName="project-file-size-calculator",
  Runtime="python3.12",
  Handler="bootstrap.handler",
  Role=<role arn above>,
)
-> arn:aws:lambda:us-east-1:913524931380:function:project-file-size-calculator

lambda.add_permission(Principal="s3.amazonaws.com", SourceArn=bucket_arn)
s3.put_bucket_notification_configuration(
  LambdaFunctionConfigurations=[{
    Events: ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"],
    Filter: prefix "projects/"
  }]
)
```
Verified via `get_bucket_notification_configuration` — trigger is live.

## Bugs found & fixed while wiring the app to real AWS

None of these are LocalStack-specific — they were latent bugs never exercised before because
the app had only ever run inside `docker compose` against LocalStack/moto:

1. **`get_s3_client()` didn't support STS session tokens**
   ([s3_service.py](app/services/s3_service.py)) — sandbox credentials are temporary
   (`AWS_SESSION_TOKEN` required); added `aws_session_token` to `Settings` and passed it
   through to `boto3.client()`.
2. **Alembic env.py stripped `+asyncpg` from the DB URL** ([env.py](app/db/migrations/env.py))
   before handing it to `async_engine_from_config`, which then tried to import the sync
   `psycopg2` driver and crashed. Removed the `.replace("+asyncpg", "")`.
3. **`project_role` enum created twice** in migration 0001 — once via manual
   `op.execute("CREATE TYPE ...")`, once implicitly by `sa.Enum(...)` inside
   `op.create_table(...)`, causing `DuplicateObjectError`. Removed the manual statement and
   let the column definition own type creation.
4. **`Settings` rejected `.env`'s `POSTGRES_*` vars** (`extra="forbid"` default in a newer
   `pydantic-settings`) — those vars are docker-compose-only convenience vars, never read by
   the app. Added `extra="ignore"` to `model_config`.

None of these affect business logic — only how config/migrations reach the process.

## Step 5 — Demo scenario against real AWS

Ran the full stack outside Docker (local `python:3.10-slim` pull was timing out on this
machine — unrelated Docker registry issue) — Postgres 16 in a plain `docker run` container,
FastAPI via `uvicorn` directly, real AWS creds exported as env vars.

```
$ curl -X POST /api/v1/auth/register  {"login":"demo_user_aws", ...}
201 {"id":"47d5ac4d-...", "login":"demo_user_aws", ...}

$ curl -X POST /api/v1/auth/login
200 {"access_token": "...", "access_expires_in": 3600, "refresh_expires_in": 604800, ...}
   # access_expires_in=3600 confirms the JWT-lasts-1-hour spec requirement (was 15 min)

$ curl -X POST /api/v1/projects  {"name":"AWS Sandbox Demo Project", ...}
201 {"id":"d6489ac5-b2bd-4029-96f1-6249b9438061", "total_size_bytes":0, ...}

$ curl -X POST /api/v1/projects/{id}/documents -F files=@demo-upload.pdf
200 [{"id":"e9650daf-...", "filename":"demo-upload.pdf", "size_bytes":63, ...}]

# verified directly against S3 (not just the API's word for it):
$ python3 -c "s3.list_objects_v2(Bucket='project-mgmt-docs-f4a8baae', Prefix='projects/d6489ac5.../')"
projects/d6489ac5-b2bd-4029-96f1-6249b9438061/documents/e9650daf-.../demo-upload.pdf  63 bytes

# CloudWatch Logs for project-file-size-calculator — confirms S3 ObjectCreated correctly
# triggered Lambda with the real, API-generated key:
[INFO] Processing S3 event for key: projects/d6489ac5-.../documents/e9650daf-.../demo-upload.pdf
[ERROR] Error processing record: connection to server at "localhost" ... Connection refused
  # expected — no RDS in this sandbox (see SCP denial above); Lambda's DB-write step needs a
  # VPC-reachable Postgres in production. The trigger wiring and key-parsing are proven live.

$ curl -X GET /api/v1/documents/{id}          -> 200, presigned S3 URL returned
$ curl -X GET /api/v1/projects/{id}/storage   -> {"total_size_bytes":63, "limit_mb":100, ...}
$ curl -X GET /api/v1/projects                -> project listed with its document, size synced
```

Confirms end-to-end: real JWT auth (1h expiry) → real Postgres → real S3 upload → real S3
event → real Lambda invocation with correctly-parsed project/document IDs → presigned
download URL → storage-limit accounting, all against actual AWS in `us-east-1`, zero
"epam" in any resource name.

## Step 6 — Test suite run

```
$ python3 -m pytest -q
80 passed in 29.19s
```
75 original tests pass unchanged against the new real-AWS config (no LocalStack coupling —
they mock via `moto`, confirmed at Step 1). 2 tests needed a one-line update because the JWT
expiry spec fix (15min → 60min) changed an expected value; not a regression, an intentional
spec-compliance change. 5 new tests added for the optional share-link feature (see below).

## Console screenshots (captured live in-session)

Logged in via the AWS federation endpoint (`signin.aws.amazon.com/federation`, temporary
STS session → console signin token, no password), saved as actual PNG files via headless
Chrome (driven over the DevTools Protocol so each capture waits for the real content to
render, not just page load):

- [docs/screenshots/s3-bucket.png](docs/screenshots/s3-bucket.png) — `project-mgmt-docs-f4a8baae`
  bucket, `demo-upload.pdf` object (63 B).
- [docs/screenshots/lambda-function.png](docs/screenshots/lambda-function.png) —
  `project-file-size-calculator` function overview, ARN, function-diagram showing the live
  S3 trigger.
- [docs/screenshots/cloudwatch-logs.png](docs/screenshots/cloudwatch-logs.png) —
  `/aws/lambda/project-file-size-calculator` log group, both real invocations
  (`INIT_START` → `START` → `[ERROR]` → `END` → `REPORT`), RequestIds matching the
  CLI-captured logs above.

## Spec-compliance improvements (beyond the AWS migration)

While reviewing against the final-project task description for max score:

1. **JWT access token now expires in 1 hour** (was 15 min) — [config.py](app/core/config.py),
   matching "JWT should last 1 hour" in the spec. Refresh-token rotation (7-day) kept as an
   additional security layer beyond the spec's minimum.
2. **Optional `GET /projects/{id}/share?with=<email>` implemented** — generates a random,
   SHA-256-hashed join token (same pattern as the existing refresh-token store), emails a
   join link (via the existing notification stub), and `GET /join?token=...` redeems it to
   grant participant access. New table `project_share_tokens` (migration `0003`), new
   [share_service.py](app/services/share_service.py), 5 new tests in
   [test_share.py](tests/integration/test_share.py).

   Live-verified against the same running instance (real AWS S3, real Postgres):
   ```
   $ curl -G /api/v1/projects/{id}/share --data-urlencode "with=colleague@example.com"
   {"join_url":"/api/v1/join?token=SEdsIw6a...", "expires_at":"2026-08-16T11:45:07Z"}

   $ curl -G /api/v1/join --data-urlencode "token=SEdsIw6a..." (as second user)
   {"project_id":"d6489ac5-...", "role":"participant", "message":"Successfully joined project"}

   $ curl /api/v1/projects/{id}/info (as second user)
   200 — project now visible to the joined user
   ```
