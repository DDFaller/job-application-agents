"""France Travail API client and models."""

from .client import (
    FRANCE_TRAVAIL_API_BASE_URL,
    FRANCE_TRAVAIL_SCOPE,
    FRANCE_TRAVAIL_TOKEN_URL,
    FranceTravailClient,
    normalize_france_travail_offer,
)
from .models import FranceTravailOffer, FranceTravailSearchParams, france_travail_public_url

__all__ = [
    "FRANCE_TRAVAIL_API_BASE_URL",
    "FRANCE_TRAVAIL_SCOPE",
    "FRANCE_TRAVAIL_TOKEN_URL",
    "FranceTravailClient",
    "FranceTravailOffer",
    "FranceTravailSearchParams",
    "france_travail_public_url",
    "normalize_france_travail_offer",
]
