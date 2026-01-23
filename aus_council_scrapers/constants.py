import re

COUNCIL_HOUSING_REGEX = [
    # Zones
    r"zoning|zone",
    # Dwellings
    r"dwelling|house|home|apartment|unit|townhouse|residential|housing|accommodation|room|studio|flat",
    # Heritage
    r"heritage|historical|cultural",
    # Density
    r"dense|densification|densities|density|densify",
    # Setbacks
    r"setback",
    # Height
    r"height",
    # Character
    r"character",
    # Yimby
    "yimby",
    # Nimby
    "nimby",
    # Legal
    r"vcat",
    # Planning and development
    r"plan|develop",
    # Housing affordability
    r"affordable\s+housing|social\s+housing|affordibility|public\s+housing",
]

# Time regex - should handle messy time strings like these:
# Part 1: (?:\d{1,2})(?::|\.)(?:\d{2}) -- This part matches the time in the format HH:MM or HH.MM
# Part 2: (?:\d{1,2})(?:(?::|\.)(?:\d{2}))?(?:\s*(?:am|pm|a\.m\.|p\.m\.)) -- This part matches the time in the format HH:MM AM/PM or HH.MM AM/PM or HH AM/PM
TIME_REGEX = re.compile(
    r"\b(?:\d{1,2})(?:(?::|\.)(?:\d{2}))?(?:\s*(?:am|pm|a\.m\.|p\.m\.))\b|\b(?:\d{1,2})(?::|\.)(?:\d{2})\b",
    re.IGNORECASE,
)


# Comprehensive date regex should handle messy dates:
# Part 1: \b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\b
#  - Monday, 25 December 2024
#  - Mon, 25 Dec 2024
#  - 25th December 2024
# Part 2: \b(?:\d{1,2}\s*[\\-]\s*\d{1,2}\s*[\\-]\s*(?:\d{4}|\d{2}))\b
#  - 25-12-2024
#  - 25 - 12 - 2024
#  - 25/12/2024
#  - 25 / 12 / 23

DATE_REGEX = re.compile(
    r"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\b|\b(?:\d{1,2}\s*[\\-]\s*\d{1,2}\s*[\\-]\s*(?:\d{4}|\d{2}))\b",
    re.IGNORECASE,
)

TIMEZONES_BY_STATE = {
    "NSW": "Australia/Sydney",
    "VIC": "Australia/Melbourne",
    "QLD": "Australia/Brisbane",
    "SA": "Australia/Adelaide",
    "WA": "Australia/Perth",
    "TAS": "Australia/Hobart",
    "NT": "Australia/Darwin",
    "ACT": "Australia/Sydney",
}

# Earliest year to fetch meeting data from
EARLIEST_YEAR = 2020
