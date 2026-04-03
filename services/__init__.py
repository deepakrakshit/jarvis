# ==============================================================================
# File: services/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Services Layer Package Initializer
#
#    - Exports primary service classes for the JARVIS service architecture.
#    - WeatherService: Open-Meteo backed weather intelligence and forecasting.
#    - NetworkService: network diagnostics, IP lookup, speed testing, system status.
#    - SearchService: Gemini Grounding powered real-time internet search.
#    - Acts as the service discovery layer for the tool registry binding.
#    - Each service is independently testable with its own HTTP client.
#    - Designed for horizontal extensibility — new services are added here.
#    - No circular dependencies — services only depend on core/ and utils/.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from services.network_service import NetworkService
from services.search_service import SearchService
from services.weather_service import WeatherService

__all__ = ["WeatherService", "NetworkService", "SearchService"]
