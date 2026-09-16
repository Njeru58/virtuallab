from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from django.utils.deconstruct import deconstructible
from django.views.decorators.cache import cache_control
from django.urls import reverse


@deconstructible
class DatabaseStorage(Storage):
    """
    Custom storage backend that saves uploaded files directly into DBStoredImage.
    Serves via dbmedia_view using normalized URLs (no trailing slash).
    """

    def _open(self, name, mode='rb'):
        from .models import DBStoredImage
        obj = DBStoredImage.objects.get(name=name)
        return ContentFile(obj.data)

    def _save(self, name, content):
        from .models import DBStoredImage
        DBStoredImage.objects.update_or_create(
            name=name,
            defaults={
                "content_type": getattr(content, "content_type", ""),
                "data": b"".join(chunk for chunk in content.chunks()),
            }
        )
        return name

    def exists(self, name):
        from .models import DBStoredImage
        return DBStoredImage.objects.filter(name=name).exists()

    def url(self, name):
        """
        Normalize file name and return a clean URL (no trailing slash).
        """
   
        name = str(name).strip().lstrip("/").rstrip("/")

       
        try:
            url = reverse("bank:dbmedia_view", kwargs={"filepath": name})
        except Exception:
            url = f"/dbmedia/{name}"

        
        return url.rstrip("/")