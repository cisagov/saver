"""Elasticsearch configuration helpers."""

# Standard Python Libraries
from collections.abc import Mapping
import os
import re
from urllib.parse import urlsplit, urlunsplit

ELASTICSEARCH_INDEX = "dmarc_aggregate_reports"
ELASTICSEARCH_HOST_SUFFIXES = (".es.amazonaws.com", ".es.amazonaws.com.cn")


def get_elasticsearch_delete_url(region, environment=None):
    """Return a validated Elasticsearch delete-by-query URL."""
    if not isinstance(region, str) or not region:
        raise RuntimeError("The AWS region must be configured.")
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", region) is None:
        raise ValueError("The AWS region is invalid.")

    if environment is None:
        environment = os.environ
    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a mapping")

    value = environment.get("ELASTICSEARCH_URL", "").strip()
    if not value:
        raise RuntimeError(
            "The ELASTICSEARCH_URL environment variable must be set when AWS "
            "credentials are available."
        )

    try:
        parsed = urlsplit(value)
    except ValueError as exception:
        raise ValueError("ELASTICSEARCH_URL is not a valid URL.") from exception
    if parsed.scheme != "https":
        raise ValueError("ELASTICSEARCH_URL must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("ELASTICSEARCH_URL must not contain user information.")
    if parsed.query or parsed.fragment:
        raise ValueError("ELASTICSEARCH_URL must not contain a query or fragment.")
    if parsed.path not in ("", "/"):
        raise ValueError("ELASTICSEARCH_URL must not contain a path.")

    try:
        port = parsed.port
    except ValueError as exception:
        raise ValueError("ELASTICSEARCH_URL contains an invalid port.") from exception
    if port not in (None, 443):
        raise ValueError("ELASTICSEARCH_URL port must be 443 when specified.")

    hostname = parsed.hostname
    expected_suffixes = tuple(
        f".{region}{host_suffix}" for host_suffix in ELASTICSEARCH_HOST_SUFFIXES
    )
    if hostname is None or not hostname.endswith(expected_suffixes):
        raise ValueError(
            "ELASTICSEARCH_URL must use an AWS Elasticsearch service hostname "
            "in the configured AWS region."
        )

    path = f"/{ELASTICSEARCH_INDEX}/_delete_by_query"
    return urlunsplit(("https", hostname, path, "", ""))
