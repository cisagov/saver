"""Tests for Elasticsearch configuration helpers."""

# Standard Python Libraries
from pathlib import Path
import sys

# Third-Party Libraries
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# cisagov Libraries
from elasticsearch_config import get_elasticsearch_delete_url  # noqa: E402

VALID_URL = "https://search-example123.us-east-1.es.amazonaws.com"
EXPECTED_DELETE_URL = f"{VALID_URL}/dmarc_aggregate_reports/_delete_by_query"
CHINA_URL = "https://search-example.cn-north-1.es.amazonaws.com.cn"
ES_REGION = "us-east-1"


@pytest.mark.parametrize("region", [None, ""])
def test_missing_aws_region_is_rejected(region):
    """The signing region must be configured."""
    with pytest.raises(RuntimeError, match="AWS region"):
        get_elasticsearch_delete_url(region, {"ELASTICSEARCH_URL": VALID_URL})


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_elasticsearch_url_is_rejected(value):
    """The URL is required when the helper is called."""
    environment = {} if value is None else {"ELASTICSEARCH_URL": value}

    with pytest.raises(RuntimeError, match="ELASTICSEARCH_URL"):
        get_elasticsearch_delete_url(ES_REGION, environment)


@pytest.mark.parametrize(
    "value",
    [
        VALID_URL.replace("https://", "http://"),
        "https://example.com",
        VALID_URL.replace("https://", "https://user@example.com@"),
        f"{VALID_URL}/another_index",
        f"{VALID_URL}?wait_for_completion=false",
        f"{VALID_URL}#fragment",
        f"{VALID_URL}.example.com",
        f"{VALID_URL}:80",
        f"{VALID_URL}:notaport",
        "https://[invalid",
    ],
)
def test_invalid_elasticsearch_url_is_rejected(value):
    """Unsafe Elasticsearch URLs are rejected before signing."""
    with pytest.raises(ValueError, match="ELASTICSEARCH_URL"):
        get_elasticsearch_delete_url(ES_REGION, {"ELASTICSEARCH_URL": value})


def test_elasticsearch_url_region_must_match_signing_region():
    """The endpoint and SigV4 signing regions must match."""
    with pytest.raises(ValueError, match="configured AWS region"):
        get_elasticsearch_delete_url(
            "us-west-2", {"ELASTICSEARCH_URL": VALID_URL}
        )


@pytest.mark.parametrize(
    ("region", "value", "expected"),
    [
        (ES_REGION, f" {VALID_URL}/ ", EXPECTED_DELETE_URL),
        (ES_REGION, f"{VALID_URL}:443", EXPECTED_DELETE_URL),
        (
            "cn-north-1",
            CHINA_URL,
            f"{CHINA_URL}/dmarc_aggregate_reports/_delete_by_query",
        ),
    ],
)
def test_elasticsearch_url_is_validated_and_normalized(region, value, expected):
    """Valid base URLs produce a normalized delete-by-query URL."""
    result = get_elasticsearch_delete_url(region, {"ELASTICSEARCH_URL": value})

    assert result == expected
