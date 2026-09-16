import os
from django.utils.crypto import get_random_string
from cloudinary_storage.storage import MediaCloudinaryStorage

class VideoCloudinaryStorage(MediaCloudinaryStorage):
    def _get_resource_type(self, name):
        return "video"

class CloudinaryImageStorage(MediaCloudinaryStorage):
    """
    Saves images to Cloudinary and returns the HTTPS URL immediately.
    """
    pass

class CKEditorCloudinaryStorage(MediaCloudinaryStorage):

    def _save(self, name, content):
        import os
        from django.utils.crypto import get_random_string

        content.seek(0)

        base, ext = os.path.splitext(name.replace("\\", "/"))
        unique_name = f"{base}_{get_random_string(7)}{ext}"

        return super()._save(unique_name, content)

    def url(self, name):
        return super().url(name)