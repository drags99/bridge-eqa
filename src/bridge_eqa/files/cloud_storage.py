from typing import Optional, Union
import boto3
import hashlib
from pathlib import Path
import os
import io
from PIL import Image
from pydantic import BaseModel
import diskcache as dc
import logfire
import atexit


_RECOMPRESS_SUFFIXES = {".jpg", ".jpeg", ".png"}

class CloudFileResponse(BaseModel):
    download_url: str # url to download the file
    cloud_file_name: str # name of the file in the cloud
    local_file_path: str # path to the file on the local disk

def read_file_content(file_path: Union[str, Path]) -> bytes:
    """Read and return file content as bytes."""
    return Path(file_path).read_bytes()

def calculate_content_hash(file_content):
    """Calculate SHA256 hash of file content (first 32 chars for consistency)."""
    return hashlib.sha256(file_content).hexdigest()[:32]

def create_hashed_filename(file_path: Union[str, Path], file_content: bytes) -> str:
    """Create filename using content hash and original extension."""
    content_hash = calculate_content_hash(file_content)
    file_extension = Path(file_path).suffix
    return f"{content_hash}{file_extension}"

class CloudFileStorage:
    def __init__(
        self,
        cache_dir: str = ".cache/cloud_storage",
        recompress_images: bool = True,
        jpeg_quality: int = 85,
    ):
        import dotenv
        dotenv.load_dotenv()
        self.recompress_images = recompress_images
        self.jpeg_quality = jpeg_quality
        # pyrefly: ignore [no-matching-overload]
        self.s3 = boto3.client(
            service_name=os.getenv("SERVICE_NAME"),
            endpoint_url=os.getenv("ENDPOINT_URL"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("REGION_NAME"),# probably just use auto
        )
        self.bucket_name = os.getenv("BUCKET_NAME")
        atexit.register(self.close)

        # Initialize diskcache with appropriate settings
        self.cache = dc.Cache(
            cache_dir,
            size_limit=500 * 1024 * 1024,  # 500MB cache limit
            eviction_policy='least-recently-used',
        )
        logfire.info(f"Initialized disk cache at {cache_dir}")

    def _upload_file(self, cloud_file_name: str, file_content: bytes) -> None:
        self.s3.upload_fileobj(io.BytesIO(file_content), self.bucket_name, cloud_file_name)

    def _recompress_image(self, file_path: Path, file_content: bytes) -> tuple[bytes, str]:
        """Return (content, suffix), re-encoding images to JPEG to keep request
        payloads under provider image-size limits.

        Non-images and recompression failures fall back to the original bytes.
        """
        if (
            not self.recompress_images
            or file_path.suffix.lower() not in _RECOMPRESS_SUFFIXES
        ):
            return file_content, file_path.suffix
        try:
            with Image.open(io.BytesIO(file_content)) as image:
                rgb = image.convert("RGB")
                buffer = io.BytesIO()
                rgb.save(buffer, format="JPEG", quality=self.jpeg_quality, optimize=True)
            return buffer.getvalue(), ".jpg"
        except Exception as e:
            logfire.info(f"Image recompress failed for {file_path}, using original: {e}")
            return file_content, file_path.suffix

    def _check_if_file_exists_on_cloud(self, cloud_file_name: str) -> bool:
        """
        Args:
            cloud_file_name: The hashed file name.

        Returns:
            True if the file exists, False otherwise.
        """
        # Check cache first
        cache_key = f"file_exists:{cloud_file_name}"
        cached_result = self.cache.get(cache_key)

        if cached_result is not None:
            # logfire.info(f"Cache hit: file {cloud_file_name} existence = {cached_result}")
            return cached_result

        # Not in cache, check S3
        try:
            # logfire.info(f"Cache miss: checking if file {cloud_file_name} exists on the cloud.")
            self.s3.head_object(Bucket=self.bucket_name, Key=cloud_file_name)
            exists = True
        except Exception:
            exists = False

        # Cache the result for 1 hour
        self.cache.set(cache_key, exists, expire=3600)
        # logfire.info(f"Cached file existence: {cloud_file_name} = {exists}")
        return exists
    
    def _cached_file_upload(self, file_path: Union[str, Path], file_content: Optional[bytes] = None) -> str:
        # check if the file exists
        file_path = Path(file_path)
        if not file_path.exists():
            logfire.info(f"File {file_path} does not exist")
            raise FileNotFoundError(f"File {file_path} does not exist")

        # Get file modification time for cache invalidation
        file_mtime = file_path.stat().st_mtime
        file_size = file_path.stat().st_size

        # Create cache key based on absolute path, mtime, and size. The recompress
        # setting is part of the key so toggling/retuning it invalidates stale
        # mappings (e.g. older uploads of the un-recompressed original).
        recompress_tag = f"jpeg{self.jpeg_quality}" if self.recompress_images else "raw"
        cache_key = f"upload:{file_path.absolute()}:{file_mtime}:{file_size}:{recompress_tag}"

        # Check cache for cloud_file_name
        cached_cloud_name = self.cache.get(cache_key)
        if cached_cloud_name:
            # logfire.info(f"Cache hit: file {file_path} -> {cached_cloud_name}")
            # Verify the file still exists on cloud before returning cached value
            if self._check_if_file_exists_on_cloud(cached_cloud_name):
                return cached_cloud_name
            else:
                # File was deleted from cloud, remove from cache
                self.cache.delete(cache_key)
                logfire.info(f"Cached file {cached_cloud_name} no longer exists on cloud, re-uploading")

        # load file_content to determine the cloud_file_name if not provided
        if file_content is None:
            file_content = read_file_content(file_path)

        # recompress images (e.g. PNG -> JPEG) so the uploaded object is what the
        # model provider downloads; the cloud name reflects the transformed bytes
        file_content, suffix = self._recompress_image(file_path, file_content)
        cloud_file_name = f"{calculate_content_hash(file_content)}{suffix}"

        # check if the file exists on the cloud, if not, upload it and return the cloud_file_name
        if self._check_if_file_exists_on_cloud(cloud_file_name):
            logfire.info(f"File {file_path} already exists on the cloud, skipping upload.")
        else:
            self._upload_file(cloud_file_name, file_content)
            # Update file existence cache after upload
            self.cache.set(f"file_exists:{cloud_file_name}", True, expire=3600)

        # Cache the mapping for 24 hours
        self.cache.set(cache_key, cloud_file_name, expire=86400)
        return cloud_file_name

    def get_download_url(self, file_path: Union[str, Path], expires_in: int = 3600*12) -> CloudFileResponse:
        """
        Tries to upload the file to the cloud if it doesn't exist and then returns the download url.
        Args:
            file_path: The path to the file on the local disk.
            expires_in: The number of seconds the url will be valid for.

        Returns:
            A CloudFileResponse object.

        """
        try:
            file_path = Path(file_path)
            cloud_file_name = self._cached_file_upload(file_path)

            # Create cache key for URL based on cloud file name and expiration time
            url_cache_key = f"url:{cloud_file_name}:{expires_in}"

            # Check if we have a cached URL that's still valid
            cached_response = self.cache.get(url_cache_key)
            if cached_response:
                # logfire.info(f"Cache hit: returning cached URL for {cloud_file_name}")
                # Update the local file path in case it's different
                cached_response.local_file_path = str(file_path)
                return cached_response

            # Generate new presigned URL
            # logfire.info(f"Cache miss: generating new URL for {cloud_file_name}")
            download_url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': cloud_file_name},
                ExpiresIn=expires_in
            )

            response = CloudFileResponse(
                download_url=download_url,
                cloud_file_name=cloud_file_name,
                local_file_path=str(file_path)
            )

            # Cache the response for slightly less than the URL expiration time
            # to ensure we don't serve expired URLs
            cache_duration = max(expires_in - 300, 60)  # At least 1 minute, but 5 minutes less than expiry
            self.cache.set(url_cache_key, response, expire=cache_duration)
            # logfire.info(f"Cached URL for {cloud_file_name}, expires in {cache_duration} seconds")

            return response
        except Exception as e:
            logfire.info(f"Error getting download url: {e}")
            raise e

    def clear_cache(self):
        """Clear all cached data."""
        self.cache.clear()
        logfire.info("Cache cleared")

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        stats = {
            "size": self.cache.volume(),  # Size in bytes
            "count": len(self.cache),     # Number of cached items
            "hits": self.cache.stats(enable=True, reset=False)[0],  # Cache hits
            "misses": self.cache.stats(enable=True, reset=False)[1],  # Cache misses
        }
        logfire.info(f"Cache stats: {stats}")
        return stats

    def close(self):
        """Close the cache connection."""
        if hasattr(self, 'cache'):
            self.cache.close()
            # logfire.info("Cache connection closed")
