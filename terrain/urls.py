"""
terrain/urls.py -- routes owned by the terrain app.

CREATE this file at:  worldforge/terrain/urls.py
Then include it from the ROOT urls (worldforge/config/urls.py):

    from django.urls import include, path
    urlpatterns = [
        path("admin/", admin.site.urls),
        path("", include("terrain.urls")),     # <-- add this line
    ]

The tile pattern accepts NEGATIVE z, x and y. Leaflet's CRS.Simple
legitimately requests negative tile indices and indices past the map edge;
the view answers those with a transparent PNG. The earlier 404 storm was
this regex rejecting negative x/y before the request ever reached the view.
"""

from django.urls import re_path

from . import tiles

urlpatterns = [
    re_path(
        r"^api/tiles/(?P<z>-?\d+)/(?P<x>-?\d+)/(?P<y>-?\d+)\.png$",
        tiles.tile,
        name="tile",
    ),
    # POST target for the "Run erosion" button -- the next milestone
    # (Celery task + Channels). Stubbed here so the route exists.
    # path("api/runs/", runs.create_run, name="create-run"),
]
