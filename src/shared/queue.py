import json

import boto3

from src.shared.config import settings
from src.shared.logging import logger


def _client():
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.sqs_endpoint_url,
    )


def send_message(queue_url: str, body: dict) -> None:
    _client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    logger.info("queue_message_sent", queue=queue_url)


def receive_messages(queue_url: str, max_messages: int = 10, wait_time_seconds: int = 20) -> list[dict]:
    resp = _client().receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=wait_time_seconds,
    )
    return resp.get("Messages", [])


def delete_message(queue_url: str, receipt_handle: str) -> None:
    _client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
