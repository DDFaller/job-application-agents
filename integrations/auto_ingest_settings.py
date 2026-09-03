"""Manually editable provider settings for Gmail job-alert ingestion.

Keep this file deliberately small.  The ingestion pipeline validates it before
it opens Gmail, so a typo cannot silently broaden or disable the filter.
"""

LINKEDIN = "LINKEDIN"
INDEED = "INDEED"

PROVIDERS = [
    LINKEDIN,
    INDEED,
]

matches_dict = {
    LINKEDIN: [
        "linkedin",
        "linkedinjobs",
        "linkedin job alerts",
    ],
    INDEED: [
        "indeed",
        "indeed jobs",
        "job alert",
    ],
}
