"""Query building shared by the API routers.

Every photo grid in the app (library, person, tag, event, place, folder,
large files) pages through the same photo columns with the same visibility
rule, so the select, the summary mapping and the paging live here once.
"""
