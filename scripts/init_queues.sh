#!/bin/bash
ENDPOINT=http://localhost:4566
AWS_OPTS="--endpoint-url=$ENDPOINT --region us-east-1"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test

aws $AWS_OPTS sqs create-queue --queue-name raw-items
aws $AWS_OPTS sqs create-queue --queue-name approved-drafts
aws $AWS_OPTS sqs create-queue --queue-name dlq

echo "SQS queues created in LocalStack"
