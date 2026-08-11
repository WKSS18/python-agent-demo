"""RabbitMQ topology and durable message publishing helpers."""

from __future__ import annotations

import json

import pika

from app.config import get_settings


def connect() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(get_settings().rabbitmq_url))


def declare_topology(channel) -> None:
    settings = get_settings()
    channel.exchange_declare(exchange="fieldnote.documents", exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=settings.rabbitmq_document_dlx, exchange_type="direct", durable=True)
    channel.queue_declare(queue=f"{settings.rabbitmq_document_queue}.dead", durable=True)
    channel.queue_bind(
        queue=f"{settings.rabbitmq_document_queue}.dead",
        exchange=settings.rabbitmq_document_dlx,
        routing_key="failed",
    )
    channel.queue_declare(
        queue=settings.rabbitmq_document_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.rabbitmq_document_dlx,
            "x-dead-letter-routing-key": "failed",
        },
    )
    channel.queue_bind(
        queue=settings.rabbitmq_document_queue,
        exchange="fieldnote.documents",
        routing_key="import",
    )


def publish_document_job(channel, job_id: int) -> None:
    body = json.dumps({"job_id": job_id}).encode()
    channel.basic_publish(
        exchange="fieldnote.documents", routing_key="import", body=body,
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=pika.DeliveryMode.Persistent,
            message_id=str(job_id), type="document.import",
        ),
        mandatory=True,
    )
