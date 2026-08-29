"""Run periodic synchronization of a local folder with Yandex Disk."""

from dataclasses import dataclass
import os
import sys
import time
from typing import Dict, Protocol

from dotenv import dotenv_values
from loguru import logger
import requests

from yandex_disk import CloudAuthenticationError, CloudStorageError, YandexDisk


class CloudConnector(Protocol):
    """Operations required by the synchronization algorithm."""

    def get_info(self) -> Dict[str, float]:
        """Return filenames and modification timestamps."""

    def load(self, path: str) -> None:
        """Upload a new file."""

    def reload(self, path: str) -> None:
        """Replace an existing file."""

    def delete(self, filename: str) -> None:
        """Delete a file."""


@dataclass(frozen=True)
class Config:
    """Validated application settings."""

    local_folder: str
    cloud_folder: str
    token: str
    sync_interval: float
    log_file: str


def load_config(env_path: str = ".env") -> Config:
    """Read and validate application settings from an env file."""
    values = dotenv_values(env_path)
    required_keys = (
        "LOCAL_FOLDER",
        "CLOUD_FOLDER",
        "YANDEX_TOKEN",
        "SYNC_INTERVAL",
        "LOG_FILE",
    )
    missing = [key for key in required_keys if not values.get(key)]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Заполните параметры в .env: {names}")

    local_folder = os.path.abspath(str(values["LOCAL_FOLDER"]))
    if not os.path.isdir(local_folder):
        raise ValueError(
            f"Локальная папка не найдена: {local_folder}. "
            "Проверьте LOCAL_FOLDER в .env"
        )

    try:
        sync_interval = float(str(values["SYNC_INTERVAL"]))
    except ValueError as error:
        raise ValueError("SYNC_INTERVAL должен быть числом") from error
    if sync_interval <= 0:
        raise ValueError("SYNC_INTERVAL должен быть больше нуля")

    log_file = os.path.abspath(str(values["LOG_FILE"]))
    log_directory = os.path.dirname(log_file)
    os.makedirs(log_directory, exist_ok=True)
    return Config(
        local_folder=local_folder,
        cloud_folder=str(values["CLOUD_FOLDER"]),
        token=str(values["YANDEX_TOKEN"]),
        sync_interval=sync_interval,
        log_file=log_file,
    )


def configure_logger(log_file: str) -> None:
    """Write INFO and ERROR messages to the configured file."""
    logger.remove()
    logger.add(
        log_file,
        level="INFO",
        format=(
            "synchroniser {time:YYYY-MM-DD HH:mm:ss,SSS} "
            "{level} {message}"
        ),
        encoding="utf-8",
        rotation="10 MB",
    )


def scan_local_files(folder: str) -> Dict[str, float]:
    """Return names and modification timestamps of direct child files."""
    names = os.listdir(folder)
    paths = ((name, os.path.join(folder, name)) for name in names)
    return {
        name: os.path.getmtime(path)
        for name, path in paths
        if os.path.isfile(path)
    }


def remove_cloud_only_files(
    cloud: CloudConnector,
    local_files: Dict[str, float],
    cloud_files: Dict[str, float],
) -> None:
    """Remove files that no longer exist in the local folder."""
    for filename in cloud_files.keys() - local_files.keys():
        try:
            cloud.delete(filename)
            logger.info("Файл {} успешно удалён.", filename)
        except (OSError, requests.RequestException, CloudStorageError) as error:
            logger.error("Файл {} не удалён. {}", filename, error)


def upload_local_files(
    cloud: CloudConnector,
    folder: str,
    local_files: Dict[str, float],
    cloud_files: Dict[str, float],
) -> None:
    """Upload new and changed local files."""
    for filename, modified_at in local_files.items():
        path = os.path.join(folder, filename)
        try:
            synchronize_one_file(
                cloud,
                path,
                filename,
                modified_at,
                cloud_files,
            )
        except (OSError, requests.RequestException, CloudStorageError) as error:
            logger.error("Файл {} не синхронизирован. {}", filename, error)


def synchronize_one_file(
    cloud: CloudConnector,
    path: str,
    filename: str,
    modified_at: float,
    cloud_files: Dict[str, float],
) -> None:
    """Upload one file if it is new or newer than its cloud copy."""
    if filename not in cloud_files:
        cloud.load(path)
        logger.info("Файл {} успешно записан.", filename)
        return
    if modified_at > cloud_files[filename]:
        cloud.reload(path)
        logger.info("Файл {} успешно перезаписан.", filename)


def synchronize(cloud: CloudConnector, local_folder: str) -> None:
    """Make the backup directory match the local directory."""
    try:
        cloud_files = cloud.get_info()
        local_files = scan_local_files(local_folder)
    except (OSError, requests.RequestException, CloudStorageError) as error:
        logger.error("Не удалось получить списки файлов. {}", error)
        return
    remove_cloud_only_files(cloud, local_files, cloud_files)
    upload_local_files(cloud, local_folder, local_files, cloud_files)


def run(config: Config) -> None:
    """Initialize the connector and run synchronization forever."""
    configure_logger(config.log_file)
    logger.info(
        "Программа синхронизации файлов начинает работу с директорией {}",
        config.local_folder,
    )
    cloud = YandexDisk(config.token, config.cloud_folder)
    try:
        cloud.validate_token()
        cloud.ensure_directory()
    except CloudAuthenticationError as error:
        logger.error("{}", error)
        print(f"Ошибка: {error}. Проверьте YANDEX_TOKEN в .env.")
        return
    except (requests.RequestException, CloudStorageError) as error:
        logger.error("Сервис временно недоступен. {}", error)

    try:
        while True:
            synchronize(cloud, config.local_folder)
            time.sleep(config.sync_interval)
    except KeyboardInterrupt:
        logger.info("Программа остановлена пользователем.")
        print("Синхронизация остановлена.")


def main() -> None:
    """Read settings and start the application."""
    try:
        config = load_config()
    except (OSError, ValueError) as error:
        print(f"Ошибка настройки: {error}")
        sys.exit(1)
    run(config)


if __name__ == "__main__":
    main()
