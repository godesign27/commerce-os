"""Image pipeline: versioned derivative recipes (resources/image-recipes/). Needs Pillow (.venv)."""
try:                                       # iPhone photos: Pillow reads HEIC once this is registered
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:                        # no project environment; the tests that need images are skipped
    pass
