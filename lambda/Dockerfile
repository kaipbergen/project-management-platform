FROM public.ecr.aws/lambda/python:3.10

# Install psycopg2 (sync driver for Lambda)
RUN pip install --no-cache-dir psycopg2-binary boto3

COPY lambda/file_size_calculator.py ${LAMBDA_TASK_ROOT}/

CMD ["file_size_calculator.handler"]
