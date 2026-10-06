# Cloud environment bucket storage (Yandex Cloud)

Use this reference for bucket operations belonging to a Yandex Cloud
environment. `DataLensClientYC` exposes signed URL creation, object metadata,
and key listing; the SDK does not upload or download object contents itself.
Other installations do not expose these actions. Configure the client through
[setup](setup.md).

## Signed upload and download URLs

Use the action-first create namespace:

```python
upload = client.create.bucket_upload_url(
    cloud_environment_id="environment-id",
    path="reports/result.csv",
    size="1024",
    content_md5="base64-md5",
)
download = client.create.bucket_download_url(
    cloud_environment_id="environment-id",
    path="reports/result.csv",
)
```

Both calls return a `CloudEnvironmentStorageSignedUrl` with a `.url` string.
The URL is a credential: do not print it, log it, or include it in diagnostic
output. Its representation intentionally hides the URL. Use the returned URL
with the storage operation that the caller intends to perform; the SDK does
not perform that operation for you.

## Metadata and listing

`client.get.bucket_object_metadata(cloud_environment_id, path)` returns a
`CloudEnvironmentStorageObjectMetadata` with string `.size` and optional
`.last_modified` (`LakehouseTimestamp`). `client.list.bucket_objects(...)`
returns a lazy `Pager[str]` of object keys:

```python
metadata = client.get.bucket_object_metadata("environment-id", "reports/result.csv")
keys = client.list.bucket_objects("environment-id", prefix="reports/", page_size=100)
```

Listing accepts `prefix=None`, `page_size=1000`, and `page_token=None` by
default. A supplied continuation token resumes the listing; repeated tokens
are rejected instead of looping. Constructing the pager makes no request.
Before requesting pages or inspecting metadata, ask the user how returned
data should be handled; see [core concepts](core-concepts.md) for shared pager
behavior.
