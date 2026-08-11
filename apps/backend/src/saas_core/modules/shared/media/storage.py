from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Protocol

from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.session import get_session
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class SignedUpload:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    content_length: int
    content_type: str


class ObjectNotFoundError(RuntimeError):
    pass


class ObjectTooLargeError(RuntimeError):
    pass


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    def sign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_in: int,
    ) -> SignedUpload: ...

    def head(self, *, object_key: str) -> ObjectMetadata: ...

    def read(self, *, object_key: str, max_bytes: int) -> bytes: ...

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    def delete(self, *, object_key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self) -> None:
        required = {
            "private_endpoint": settings.OBJECT_STORAGE_ENDPOINT_URL,
            "public_endpoint": settings.OBJECT_STORAGE_PUBLIC_ENDPOINT_URL,
            "bucket": settings.OBJECT_STORAGE_BUCKET,
            "access_key": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "secret_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        }
        if any(not value for value in required.values()):
            raise ImproperlyConfigured("Object storage nie jest skonfigurowany dla mediów")
        self.bucket = settings.OBJECT_STORAGE_BUCKET
        session = get_session()
        client_options = {
            "region_name": settings.OBJECT_STORAGE_REGION,
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "config": Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": (
                        "path" if settings.OBJECT_STORAGE_FORCE_PATH_STYLE else "virtual"
                    )
                },
            ),
        }
        self.public_client: BaseClient = session.create_client(
            "s3",
            endpoint_url=settings.OBJECT_STORAGE_PUBLIC_ENDPOINT_URL,
            **client_options,
        )
        self.private_client: BaseClient = session.create_client(
            "s3",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT_URL,
            **client_options,
        )

    def sign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_in: int,
    ) -> SignedUpload:
        url = self.public_client.generate_presigned_url(
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

    def head(self, *, object_key: str) -> ObjectMetadata:
        try:
            response = self.private_client.head_object(Bucket=self.bucket, Key=object_key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError(object_key) from error
            raise ObjectStorageError("Nie można odczytać metadanych obiektu.") from error
        return ObjectMetadata(
            content_length=int(response["ContentLength"]),
            content_type=str(response.get("ContentType", "")).strip().lower(),
        )

    def read(self, *, object_key: str, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("Limit odczytu obiektu musi być dodatni.")
        try:
            response = self.private_client.get_object(Bucket=self.bucket, Key=object_key)
            body = response["Body"]
            try:
                content = body.read(max_bytes + 1)
            finally:
                body.close()
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFoundError(object_key) from error
            raise ObjectStorageError("Nie można odczytać obiektu.") from error
        except (BotoCoreError, OSError) as error:
            raise ObjectStorageError("Nie można odczytać obiektu.") from error
        if len(content) > max_bytes:
            raise ObjectTooLargeError(object_key)
        return bytes(content)

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        try:
            self.private_client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError, OSError) as error:
            raise ObjectStorageError("Nie można zapisać obiektu.") from error

    def delete(self, *, object_key: str) -> None:
        try:
            self.private_client.delete_object(Bucket=self.bucket, Key=object_key)
        except (BotoCoreError, ClientError, OSError) as error:
            raise ObjectStorageError("Nie można usunąć obiektu.") from error


@cache
def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()
