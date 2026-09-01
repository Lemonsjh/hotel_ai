"""Blueprint decision modules."""

from runtime.decisions.calendar_seed_source_guard import (
    install_calendar_seed_source_guard,
)
from runtime.s4_weather_event_detail_patch import (
    install_s4_weather_event_detail_patch,
)


install_calendar_seed_source_guard()
install_s4_weather_event_detail_patch()


del install_calendar_seed_source_guard
del install_s4_weather_event_detail_patch
