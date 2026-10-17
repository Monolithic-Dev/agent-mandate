"""Thin, safe wrapper around the FalkorDB client.

Only named queries stored as ``.cypher`` files in ``graph/queries`` can be executed, and
every value travels as a parameter (docs/security-privacy.md T4). The one escape hatch,
``run_admin_text``, is for schema statements and tests.
"""

from __future__ import annotations

import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from falkordb import FalkorDB
from falkordb.edge import Edge
from falkordb.graph import Graph
from falkordb.node import Node
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from mandate.config import Settings
from mandate.errors import GraphQueryError, GraphUnavailable
from mandate.logging import get_logger
from mandate.observability import metrics

log = get_logger(__name__)

QUERY_DIR = Path(__file__).parent / "queries"
QUERY_NAME_RE = re.compile(r"^[qw]\d{2}[a-z]?_[a-z0-9_]+$")
GRAPH_NAME_RE = re.compile(r"^[a-z0-9_]{1,80}$")
CONNECT_RETRIES = 2
COPY_RETRIES = 3
BUSY_MESSAGE = "Max pending queries exceeded"
MISSING_GRAPH_MESSAGE = "Invalid graph operation on empty key"
BUSY_RETRIES = 12
BUSY_BACKOFF_SECONDS = 0.005
BUSY_BACKOFF_CAP_SECONDS = 0.2

Row = dict[str, Any]


@lru_cache(maxsize=256)
def load_query(name: str) -> str:
    """Return the text of a named query. Rejects names that are not plain identifiers."""
    if not QUERY_NAME_RE.match(name):
        raise ValueError(f"invalid query name: {name!r}")
    path = QUERY_DIR / f"{name}.cypher"
    if not path.is_file():
        raise ValueError(f"unknown query: {name!r}")
    return path.read_text(encoding="utf-8")


def validate_graph_name(name: str) -> str:
    if not GRAPH_NAME_RE.match(name):
        raise ValueError(f"invalid graph name: {name!r}")
    return name


def to_python(value: Any) -> Any:
    """Convert driver objects (nodes, edges, ordered dicts) to plain Python data."""
    if isinstance(value, Node | Edge):
        return dict(value.properties)
    if isinstance(value, OrderedDict | dict):
        return {key: to_python(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_python(item) for item in value]
    return value


class GraphClient:
    """Executes named queries against per-tenant graphs."""

    def __init__(self, db: FalkorDB, max_in_flight: int = 16) -> None:
        self._db = db
        # Backpressure: at most this many queries are outstanding from this client, so a
        # burst waits here instead of overflowing the server's own queue and being rejected.
        self._slots = threading.BoundedSemaphore(max_in_flight)

    @classmethod
    def from_settings(cls, settings: Settings) -> GraphClient:
        password = (
            settings.falkordb_password.get_secret_value() if settings.falkordb_password else None
        )
        db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            password=password,
            socket_timeout=10,
            socket_connect_timeout=5,
        )
        return cls(db, settings.falkordb_max_in_flight)

    # --- queries -----------------------------------------------------------------

    def run(
        self, graph_name: str, query_name: str, params: Mapping[str, Any] | None = None
    ) -> list[Row]:
        """Run a named query and return rows as dicts keyed by the RETURN aliases."""
        # Named reads (q*) go through GRAPH.RO_QUERY: readers run in parallel on the server and
        # a read query cannot change data even by mistake.
        return self._execute(
            graph_name,
            load_query(query_name),
            params,
            read_only=query_name.startswith("q"),
            label=query_name,
        )

    def run_admin_text(
        self, graph_name: str, query: str, params: Mapping[str, Any] | None = None
    ) -> list[Row]:
        """Run raw query text. For schema statements and tests only; never with user input."""
        return self._execute(graph_name, query, params, label="admin_text")

    def _graph(self, name: str) -> Graph:
        return self._db.select_graph(validate_graph_name(name))

    def _execute(
        self,
        graph_name: str,
        query: str,
        params: Mapping[str, Any] | None,
        *,
        read_only: bool = False,
        label: str = "unnamed",
    ) -> list[Row]:
        began = time.perf_counter()
        try:
            return self._execute_once(graph_name, query, params, read_only)
        finally:
            metrics.GRAPH_QUERY_SECONDS.labels(label, "read" if read_only else "write").observe(
                time.perf_counter() - began
            )

    def _execute_once(
        self, graph_name: str, query: str, params: Mapping[str, Any] | None, read_only: bool
    ) -> list[Row]:
        graph = self._graph(graph_name)
        attempt = 0
        busy = 0
        while True:
            try:
                with self._slots:
                    run = graph.ro_query if read_only else graph.query
                    result = run(query, dict(params or {}))
                break
            except (RedisConnectionError, RedisTimeoutError) as error:
                attempt += 1
                if attempt > CONNECT_RETRIES:
                    metrics.GRAPH_ERRORS.labels("unavailable").inc()
                    log.error("graph_unavailable", graph=graph_name)
                    raise GraphUnavailable("the graph database is unreachable") from error
                time.sleep(0.1 * attempt)
            except ResponseError as error:
                if read_only and MISSING_GRAPH_MESSAGE in str(error):
                    return []  # a graph that does not exist yet has no rows to read
                if BUSY_MESSAGE in str(error):
                    # The server refused the query without running it, so retrying is safe
                    # for reads and writes alike.
                    busy += 1
                    metrics.GRAPH_BUSY_RETRIES.inc()
                    if busy > BUSY_RETRIES:
                        metrics.GRAPH_ERRORS.labels("overloaded").inc()
                        log.error("graph_overloaded", graph=graph_name)
                        raise GraphUnavailable("the graph database is overloaded") from error
                    delay = min(BUSY_BACKOFF_CAP_SECONDS, BUSY_BACKOFF_SECONDS * 2**busy)
                    time.sleep(delay * (0.5 + random.random()))  # noqa: S311
                    continue
                metrics.GRAPH_ERRORS.labels("rejected").inc()
                raise GraphQueryError(f"the graph database rejected the query: {error}") from error
        names = [
            column[1] if isinstance(column, list | tuple) else column for column in result.header
        ]
        return [
            dict(zip(names, (to_python(value) for value in row), strict=True))
            for row in result.result_set
        ]

    # --- graph management ----------------------------------------------------------

    def create_unique_constraint(self, graph_name: str, label: str, prop: str) -> None:
        """Create a unique constraint on ``label.prop`` (created asynchronously by the server)."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", prop
        ):
            raise ValueError("invalid label or property name")
        try:
            self._graph(graph_name).create_node_unique_constraint(label, prop)
        except ResponseError as error:
            raise GraphQueryError(f"could not create constraint: {error}") from error
        except (RedisConnectionError, RedisTimeoutError) as error:
            raise GraphUnavailable("the graph database is unreachable") from error

    def ping(self) -> bool:
        try:
            self._db.list_graphs()
        except (RedisConnectionError, RedisTimeoutError, ResponseError):
            return False
        return True

    def list_graphs(self) -> list[str]:
        try:
            return [str(name) for name in self._db.list_graphs()]
        except (RedisConnectionError, RedisTimeoutError) as error:
            raise GraphUnavailable("the graph database is unreachable") from error

    def delete_graph(self, name: str) -> None:
        """Delete a graph; deleting one that does not exist is not an error."""
        try:
            self._graph(name).delete()
        except ResponseError as error:
            if "empty key" not in str(error):
                raise GraphQueryError(f"could not delete graph: {error}") from error
        except (RedisConnectionError, RedisTimeoutError) as error:
            raise GraphUnavailable("the graph database is unreachable") from error

    def copy_graph(self, source: str, destination: str) -> None:
        """Clone ``source`` to ``destination`` with GRAPH.COPY, retrying transient failures."""
        validate_graph_name(destination)
        for attempt in range(1, COPY_RETRIES + 1):
            try:
                self._graph(source).copy(destination)
                return
            except ResponseError as error:
                transient = "fork" in str(error).lower()
                if not transient or attempt == COPY_RETRIES:
                    raise GraphUnavailable(f"could not copy graph: {error}") from error
                time.sleep(0.1 * 2**attempt)
            except (RedisConnectionError, RedisTimeoutError) as error:
                raise GraphUnavailable("the graph database is unreachable") from error
