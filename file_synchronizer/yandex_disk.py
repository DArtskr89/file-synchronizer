"""Connector for the Yandex Disk REST API."""

from datetime import datetime
import os
from typing import Dict

import requests


API_URL = "https://cloud-api.yandex.net/v1/disk"


class CloudStorageError(Exception):
    """Base error raised while working with cloud storage."""


class CloudAuthenticationError(CloudStorageError):
    """The cloud token is missing, invalid, or has insufficient permissions."""


class YandexDisk:
    """Provide file operations for one directory on Yandex Disk."""

    def __init__(self, token: str, backup_directory: str) -> None:
        self.backup_directory = backup_directory.strip("/")
        self.headers = {"Authorization": f"OAuth {token}"}
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def validate_token(self) -> None:
        """Check whether the configured OAuth token can access Yandex Disk."""
        response = self.session.get(API_URL, timeout=20)
        self._raise_for_status(response, "Не удалось проверить токен")

    def ensure_directory(self) -> None:
        """Create the backup directory when it does not exist."""
        response = self.session.get(
            f"{API_URL}/resources",
            params={"path": self.backup_directory},
            timeout=20,
        )
        if response.status_code == 404:
            self._create_directory()
            return
        self._raise_for_status(response, "Не удалось проверить папку в облаке")

    def load(self, path: str) -> None:
        """Upload a new local file to the backup directory."""
        self._upload(path, overwrite=False)

    def reload(self, path: str) -> None:
        """Replace an existing cloud file with its current local version."""
        self._upload(path, overwrite=True)

    def delete(self, filename: str) -> None:
        """Delete a file from the backup directory."""
        response = self.session.delete(
            f"{API_URL}/resources",
            params={
                "path": self._remote_path(filename),
                "permanently": "true",
            },
            timeout=20,
        )
        self._raise_for_status(response, f"Не удалось удалить файл {filename}")

    def get_info(self) -> Dict[str, float]:
        """Return cloud filenames mapped to their modification timestamps."""
        response = self.session.get(
            f"{API_URL}/resources",
            params={
                "path": self.backup_directory,
                "fields": "_embedded.items.name,_embedded.items.modified",
                "limit": 10000,
            },
            timeout=20,
        )
        self._raise_for_status(
            response,
            "Не удалось получить список файлов из облака",
        )
        items = response.json().get("_embedded", {}).get("items", [])
        return {
            item["name"]: self._to_timestamp(item["modified"])
            for item in items
            if "name" in item and "modified" in item
        }

    def _upload(self, path: str, overwrite: bool) -> None:
        filename = os.path.basename(path)
        response = self.session.get(
            f"{API_URL}/resources/upload",
            params={
                "path": self._remote_path(filename),
                "overwrite": str(overwrite).lower(),
            },
            timeout=20,
        )
        self._raise_for_status(
            response,
            f"Не удалось получить ссылку для загрузки {filename}",
        )
        upload_url = response.json().get("href")
        if not upload_url:
            raise CloudStorageError(
                f"Яндекс Диск не вернул ссылку для загрузки {filename}"
            )

        with open(path, "rb") as local_file:
            upload_response = requests.put(
                upload_url,
                data=local_file,
                timeout=120,
            )
        self._raise_for_status(
            upload_response,
            f"Не удалось загрузить файл {filename}",
        )

    def _create_directory(self) -> None:
        response = self.session.put(
            f"{API_URL}/resources",
            params={"path": self.backup_directory},
            timeout=20,
        )
        self._raise_for_status(response, "Не удалось создать папку в облаке")

    def _remote_path(self, filename: str) -> str:
        return f"{self.backup_directory}/{filename}"

    @staticmethod
    def _to_timestamp(value: str) -> float:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()

    @staticmethod
    def _raise_for_status(response: requests.Response, message: str) -> None:
        if response.status_code in (401, 403):
            raise CloudAuthenticationError(
                "Неверный токен Яндекс Диска или недостаточно прав доступа"
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise CloudStorageError(
                f"{message}. HTTP {response.status_code}"
            ) from error
