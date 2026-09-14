from abc import ABC, abstractmethod
from datetime import datetime

from hydropulse.domain import WeatherFeature


class WeatherAdapter(ABC):
    provider: str

    @abstractmethod
    async def features(
        self, basin_slug: str, start: datetime, end: datetime
    ) -> list[WeatherFeature]: ...


class AORCAdapter(WeatherAdapter):
    provider = "aorc"

    async def features(
        self, basin_slug: str, start: datetime, end: datetime
    ) -> list[WeatherFeature]:
        raise NotImplementedError(
            "Run the bounded extraction benchmark and configure Zarr object versions first"
        )


class MRMSAdapter(WeatherAdapter):
    provider = "mrms"

    async def features(
        self, basin_slug: str, start: datetime, end: datetime
    ) -> list[WeatherFeature]:
        raise NotImplementedError("MRMS requires whole-gzip download and configured basin masks")


class HRRRAdapter(WeatherAdapter):
    provider = "hrrr"

    async def features(
        self, basin_slug: str, start: datetime, end: datetime
    ) -> list[WeatherFeature]:
        raise NotImplementedError("HRRR requires .idx range qualification for the requested era")
