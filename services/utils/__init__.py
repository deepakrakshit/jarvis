# ==============================================================================
# File: services/utils/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Service Utilities Package Initializer
#
#    - Exports shared utility classes for the services layer.
#    - HttpClient: configurable HTTP client for external API calls.
#    - LocationInfo: geolocation data model with coordinates and timezone.
#    - resolve_ip_location(): IP-based geolocation with provider fallback.
#    - Provides common infrastructure used across all service modules.
#    - No dependency on other JARVIS packages for clean layering.
#    - Standardized error handling conventions for HTTP operations.
#    - Thread-safe implementations for concurrent service usage.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from services.utils.http_client import HttpClient
from services.utils.location_utils import LocationInfo, geocode_city_open_meteo, resolve_ip_location

__all__ = ["HttpClient", "LocationInfo", "geocode_city_open_meteo", "resolve_ip_location"]
