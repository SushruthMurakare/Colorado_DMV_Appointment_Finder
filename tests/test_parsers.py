"""
Unit tests for dmv.py HTML parser functions.
No network calls — all tests use inline HTML fixtures.
"""
import pytest
from datetime import datetime
from dmv import (
    extract,
    extract_csrf,
    parse_appointment_types,
    parse_available_dates,
    is_sub_unit_page,
    pick_dl_sub_unit,
)


# ── extract ───────────────────────────────────────────────────────────────────

class TestExtract:
    def test_name_before_value(self):
        html = '<input name="formJourney" value="abc-123">'
        assert extract(html, "formJourney") == "abc-123"

    def test_value_before_name(self):
        html = '<input value="xyz-789" name="formJourney">'
        assert extract(html, "formJourney") == "xyz-789"

    def test_with_extra_attributes(self):
        html = '<input type="hidden" name="StepId" id="step" value="step-001">'
        assert extract(html, "StepId") == "step-001"

    def test_empty_value(self):
        html = '<input name="formJourney" value="">'
        assert extract(html, "formJourney") == ""

    def test_missing_field_returns_none(self):
        html = '<input name="other" value="val">'
        assert extract(html, "formJourney") is None

    def test_empty_html_returns_none(self):
        assert extract("", "formJourney") is None


# ── extract_csrf ──────────────────────────────────────────────────────────────

class TestExtractCsrf:
    def test_name_before_value(self):
        html = '<input name="__RequestVerificationToken" type="hidden" value="TOKEN123">'
        assert extract_csrf(html) == "TOKEN123"

    def test_value_before_name(self):
        html = '<input value="TOKEN456" type="hidden" name="__RequestVerificationToken">'
        assert extract_csrf(html) == "TOKEN456"

    def test_returns_last_when_multiple(self):
        # Pages sometimes have two tokens; the last one is the active one
        html = (
            '<input name="__RequestVerificationToken" type="hidden" value="FIRST">'
            '<input name="__RequestVerificationToken" type="hidden" value="LAST">'
        )
        assert extract_csrf(html) == "LAST"

    def test_missing_returns_none(self):
        html = "<html><body>No token here</body></html>"
        assert extract_csrf(html) is None


# ── parse_appointment_types ───────────────────────────────────────────────────

APPT_TYPES_HTML = """
<div class="someWrapper">
  <div class="QflowObjectItem foo DataControlBtn bar" data-id="10">
    <p>Written Test</p>
  </div>
  <div class="QflowObjectItem DataControlBtn" data-id="20">
    <p>CDL Written Test</p>
  </div>
  <div class="QflowObjectItem DataControlBtn" data-id="30">
    <p>First Time CO DL/ID/Permit</p>
  </div>
</div>
"""

class TestParseAppointmentTypes:
    def test_finds_all_types(self):
        types = parse_appointment_types(APPT_TYPES_HTML)
        assert len(types) == 3

    def test_correct_ids(self):
        types = parse_appointment_types(APPT_TYPES_HTML)
        ids = [t["id"] for t in types]
        assert ids == ["10", "20", "30"]

    def test_correct_names(self):
        types = parse_appointment_types(APPT_TYPES_HTML)
        names = [t["name"] for t in types]
        assert "Written Test" in names
        assert "CDL Written Test" in names
        assert "First Time CO DL/ID/Permit" in names

    def test_strips_whitespace_from_names(self):
        html = '<div class="QflowObjectItem DataControlBtn" data-id="5"><p>  Written Test  </p></div>'
        types = parse_appointment_types(html)
        assert types[0]["name"] == "Written Test"

    def test_empty_html_returns_empty_list(self):
        assert parse_appointment_types("") == []

    def test_no_matching_divs_returns_empty(self):
        html = '<div class="SomethingElse" data-id="1"><p>Not a type</p></div>'
        assert parse_appointment_types(html) == []


# ── parse_available_dates ─────────────────────────────────────────────────────

class TestParseAvailableDates:
    def test_data_datetime_with_seconds(self):
        html = '<td data-datetime="07/15/2026 10:30:00 AM"></td>'
        dates = parse_available_dates(html)
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 7, 15, 10, 30, 0)

    def test_data_datetime_without_seconds(self):
        html = '<td data-datetime="07/15/2026 2:00 PM"></td>'
        dates = parse_available_dates(html)
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 7, 15, 14, 0)

    def test_single_datetime_class(self):
        html = '<span class="SingleDateTime">08/01/2026 09:00:00 AM</span>'
        dates = parse_available_dates(html)
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 8, 1, 9, 0, 0)

    def test_data_date_attribute(self):
        html = '<td data-date="2026-09-10" class="available"></td>'
        dates = parse_available_dates(html)
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 9, 10)

    def test_disabled_data_date_excluded(self):
        html = '<td data-date="2026-09-10" class="disabled"></td>'
        dates = parse_available_dates(html)
        assert dates == []

    def test_multiple_dates_sorted(self):
        html = (
            '<td data-datetime="08/05/2026 10:00:00 AM"></td>'
            '<td data-datetime="07/20/2026 09:00:00 AM"></td>'
            '<td data-datetime="08/01/2026 02:00:00 PM"></td>'
        )
        dates = parse_available_dates(html)
        assert dates == sorted(dates)
        assert dates[0] == datetime(2026, 7, 20, 9, 0, 0)

    def test_deduplicates_same_datetime(self):
        html = (
            '<td data-datetime="07/15/2026 10:00:00 AM"></td>'
            '<td data-datetime="07/15/2026 10:00:00 AM"></td>'
        )
        dates = parse_available_dates(html)
        assert len(dates) == 1

    def test_empty_html_returns_empty(self):
        assert parse_available_dates("") == []

    def test_no_dates_returns_empty(self):
        html = "<html><body><p>No slots available</p></body></html>"
        assert parse_available_dates(html) == []


# ── is_sub_unit_page / pick_dl_sub_unit ───────────────────────────────────────

SUB_UNIT_HTML = """
<div class="QflowObjectItem DataControlBtn" data-id="1">
  <p>Driver License</p>
</div>
<div class="QflowObjectItem DataControlBtn" data-id="2">
  <p>Vehicle Services</p>
</div>
"""

NORMAL_SERVICE_HTML = """
<div class="QflowObjectItem DataControlBtn" data-id="10">
  <p>Written Test</p>
</div>
<div class="QflowObjectItem DataControlBtn" data-id="20">
  <p>CDL Written Test</p>
</div>
"""

class TestIsSubUnitPage:
    def test_detects_sub_unit_page(self):
        assert is_sub_unit_page(SUB_UNIT_HTML) is True

    def test_normal_service_page_is_not_sub_unit(self):
        assert is_sub_unit_page(NORMAL_SERVICE_HTML) is False

    def test_empty_html_is_not_sub_unit(self):
        assert is_sub_unit_page("") is False


class TestPickDlSubUnit:
    def test_picks_driver_license_option(self):
        result = pick_dl_sub_unit(SUB_UNIT_HTML)
        assert result is not None
        assert "driver license" in result["name"].lower()

    def test_returns_none_on_empty_html(self):
        assert pick_dl_sub_unit("") is None

    def test_falls_back_to_first_item_when_no_keyword_match(self):
        html = """
        <div class="QflowObjectItem DataControlBtn" data-id="99">
          <p>Some Unknown Category</p>
        </div>
        """
        result = pick_dl_sub_unit(html)
        assert result is not None
        assert result["id"] == "99"
