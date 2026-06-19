#!/bin/bash
export APP_ENV=testing
export DATABASE_URL="sqlite+aiosqlite:///:memory:"
export SECRET_KEY="test-secret-key-32-chars-minimum!!"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export S3_BUCKET_NAME=test-bucket
pytest tests/ -v --no-cov
