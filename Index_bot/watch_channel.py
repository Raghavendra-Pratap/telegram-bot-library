"""
Watch channel publishing (catalog cards). See watch_catalog.py for implementation.
"""
from watch_catalog import (
    maybe_auto_publish_catalog_for_upload,
    publish_catalog_slot,
    publish_unpublished_catalog_batch,
)

# Backward-compatible alias
maybe_auto_publish_watch = maybe_auto_publish_catalog_for_upload
publish_unpublished_batch = publish_unpublished_catalog_batch
