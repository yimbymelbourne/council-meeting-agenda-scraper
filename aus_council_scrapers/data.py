from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import datetime
from dateutil.parser import parse as parse_date
import json
import pytz
import re
from typing import Any, Dict, Generator, List, Optional, Self

from .constants import TIMEZONES_BY_STATE

Results = Generator[ScraperResult.Notice, None]

@dataclass
class NoticeHydrationInputs:
    name: Optional[str] = field(default=None)
    location: Optional[str] = field(default=None)

    def with_location(self: Self, location: str) -> Self:
        self.location = location
        return self

    def with_name(self: Self, name: str) -> Self:
        self.name = name
        return self

class ScraperResult:
    @dataclass
    class Notice:
        name: Optional[str]
        datetime: 'NoticeDate.Base'
        location: Optional['NoticeLocation.Base']

        def hydrate(self: Self, hydration: NoticeHydrationInputs):
            if not self.name and hydration.name:
                self.name = hydration.name
            if not self.location and hydration.location:
                self.location = NoticeLocation.Raw(hydration.location)

        def to_dict(self: Self):
            return {
                "kind": "notice",
                "name": self.name,
                "date": self.datetime.date,
                "time": self.datetime.time,
                "location": self.location,
            }

        def __str__(self: Self):
            return json.dumps(self.to_dict(), indent=2)

        def check_required_properties(self, state: str) -> None:
            if not self.name or self.name.isspace():
                raise ValueError(f"No name found")

            _ = self.datetime.date

            # Check if date is in the past
            # TODO: Do we want to add this check to make sure we're not scraping meetings that happened in the past?
            # if self.is_date_in_past(state):
            #     raise ValueError(f"Meeting date is in the past")

    @dataclass
    class CouncilMeetingNotice(Notice):
        webpage_url: str
        download_url: Optional[str]

        def check_required_properties(self, state: str) -> None:
            super().check_required_properties(state)
            if not self.download_url or self.download_url.isspace():
                raise ValueError(f"No download URL found")
            if not self.webpage_url or self.webpage_url.isspace():
                raise ValueError(f"No webpage URL found")

        @staticmethod
        def from_dict(d: Dict[str, Any]):
            return ScraperResult.CouncilMeetingNotice(
                name=d["name"],
                datetime=NoticeDate.from_dict(d["datetime"]),
                webpage_url=d["webpage_url"],
                download_url=d["download_url"],
                location=NoticeLocation.from_dict(d["location"]),
            )


        def to_dict(self: Self):
            return {
                **super().to_dict(),
                "kind": "council-meeting",
                "webpage_url": self.webpage_url,
                "download_url": self.download_url,
            }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> ScraperResult.Notice:
        match d.get("kind", None):
            case None:
                return ScraperResult.CouncilMeetingNotice(
                    name=d["name"],
                    datetime=NoticeDate.FuzzyRaw(d["date"], d["time"]),
                    webpage_url=d["webpage_url"],
                    download_url=d["download_url"],
                    location=NoticeLocation.Raw(d.get("location")),
                )

            case "council-meeting":
                return ScraperResult.CouncilMeetingNotice.from_dict(d)

            case "notice":
                return ScraperResult.CouncilMeetingNotice.from_dict(d)

            case _:
                raise ValueError("nonexhaustive parser")

class NoticeLocation:
    class Base(ABC):
        @abstractmethod
        def to_dict(self: Self) -> Dict[str, str]:
            pass

        @property
        @abstractmethod
        def location_string(self: Self) -> Optional[str]:
            pass

    @dataclass
    class Raw(Base):
        raw: Optional[str]

        def to_dict(self: Self) -> Dict[str, str]:
            raise NotImplementedError('yet')

        @property
        def location_string(self: Self) -> Optional[str]:
            if not self.raw or self.raw.isspace():
                return None

            cleaned = self.raw.replace(r"\w", " ").strip().lower()

            # Remove council chambers string from location
            council_chamber_regex = re.compile(r"^council\s?chambers?,?", re.IGNORECASE)
            cleaned = council_chamber_regex.sub("", cleaned)

            if cleaned == "":
                return None

            return " ".join((word.capitalize() for word in cleaned.split()))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> NoticeLocation.Base:
        raise NotImplementedError('yet')

class NoticeDate:
    class Base(ABC):
        @property
        @abstractmethod
        def time(self) -> Optional[datetime.time]:
            pass

        @property
        @abstractmethod
        def date(self) -> datetime.date:
            pass

        @abstractmethod
        def to_dict(self: Self) -> Dict[str, str]:
            pass

        def has_transpired(self, state: str) -> bool:
            timezone = pytz.timezone(TIMEZONES_BY_STATE[state.upper()])
            today = datetime.datetime.now(timezone).date()
            return self.date < today

    @dataclass
    class SimpleDate(Base):
        date: datetime.date
        time: Optional[datetime.time]

        def to_dict(self: Self) -> Dict[str, str]:
            raise NotImplementedError('yet')

    @dataclass
    class FuzzyRaw(Base):
        raw_date: Optional[str]
        raw_time: Optional[str]
        _cleaned_time: Optional[datetime.time] = field(default=None)
        _cleaned_date: Optional[datetime.date] = field(default=None)

        @property
        def time(self) -> Optional[datetime.time]:
            try:
                if not self.raw_time:
                    return None
                if not self._cleaned_time:
                    self._cleaned_time = parse_date(self.raw_time, fuzzy=True).time()
                return self._cleaned_time
            except Exception as e:
                return None

        @property
        def date(self) -> datetime.date:
            if not self.raw_date:
                raise ValueError("Date is required")

            try:
                if not self._cleaned_date:
                    self._cleaned_date = parse_date(self.raw_date, fuzzy=True).date()
            except Exception as e:
                raise ValueError(f"Could not parse date {self.date}")

            return self._cleaned_date

        def to_dict(self: Self) -> Dict[str, str]:
            raise NotImplementedError('yet')

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> NoticeDate.Base:
        raise NotImplementedError('yet')


