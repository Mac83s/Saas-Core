from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Protocol

from botocore.client import BaseClient
from botocore.config import Config
from botocore.session import get_session
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class SignedUpload:
    url: str
    headers: dict[str, str]


class ObjectStorage(Protocol):
    def sign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_in: int,
    ) -> SignedUpload: ...


class S3ObjectStorage:
    def __init__(self) -> None:
        required = {
            "endpoint": settings.OBJECT_STORAGE_PUBLIC_ENDPOINT_URL,
            "bucket": settings.OBJECT_STORAGE_BUCKET,
            "access_key": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "secret_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        }
        if any(not value for value in required.values()):
            raise ImproperlyConfigured("Object storage nie jest skonfigurowany dla mediów")
        self.bucket = settings.OBJECT_STORAGE_BUCKET
        session = get_session()
        self.client: BaseClient = session.create_client(
            "s3",
            endpoint_url=settings.OBJECT_STORAGE_PUBLIC_ENDPOINT_URL,
            region_name=settings.OBJECT_STORAGE_REGION,
            aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": (
                        "path" if settings.OBJECT_STORAGE_FORCE_PATH_STYLE else "virtual"
                    )
                },
            ),
        )

    def sign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_in: int,
    ) -> SignedUpload:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
        return SignedUpload(url=url, headers={"Content-Type": content_type})


@cache
def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()
