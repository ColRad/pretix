import hashlib
import logging
import os

import django_libsass
import sass
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from pretix.base.models import Event

logger = logging.getLogger('pretix.presale.style')


def regenerate_css(event_id: int):
    event = Event.objects.select_related('organizer').get(pk=event_id)
    sassdir = os.path.join(settings.STATIC_ROOT, 'pretixpresale/scss')

    sassrules = [
        '$brand-primary: {};'.format(event.settings.get('primary_color')),
        '@import "main.scss";',
    ]

    css = sass.compile(
        string="\n".join(sassrules),
        include_paths=[sassdir], output_style='compressed',
        custom_functions=django_libsass.CUSTOM_FUNCTIONS
    )
    checksum = hashlib.sha1(css.encode('utf-8')).hexdigest()
    fname = '{}/{}/presale.{}.css'.format(
        event.organizer.slug, event.slug, checksum[:16]
    )

    if event.settings.get('presale_css_checksum', '') != checksum:
        newname = default_storage.save(fname, ContentFile(css))
        event.settings.set('presale_css_file', newname)
        event.settings.set('presale_css_checksum', checksum)


if settings.HAS_CELERY:
    from pretix.celery import app

    regenerate_css_task = app.task(regenerate_css)

    def regenerate_css(*args, **kwargs):
        regenerate_css_task.apply_async(args=args, kwargs=kwargs)
