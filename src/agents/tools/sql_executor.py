from typing import Any, Mapping, Sequence

import pandas as pd
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


# Custom exceptions for SQL Executor
class SQLExecutorException(Exception):
    """Base exception for SQL Executor errors"""

    pass


class DatabaseConnectionException(SQLExecutorException):
    """Exception raised when database connection fails"""

    pass


class QueryExecutionException(SQLExecutorException):
    """Exception raised when query execution fails"""

    pass


class QueryTimeoutException(QueryExecutionException):
    """Exception raised when query execution times out"""

    pass


class InvalidQueryException(QueryExecutionException):
    """Exception raised when query syntax is invalid"""

    pass


class PermissionDeniedException(QueryExecutionException):
    """Exception raised when permission is denied for query"""

    pass


class SQLExecutor:
    """
    Asynchronous SQL executor -> pandas.DataFrame.
    """

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        url: str | URL | None = None,
        **engine_kwargs: Any,
    ) -> None:
        if engine is None and url is None:
            raise SQLExecutorException(
                "SQL Executor requires either an AsyncEngine or a database URL. "
                "Please provide one of these parameters."
            )
        try:
            self._engine: AsyncEngine = engine or create_async_engine(
                url, **engine_kwargs
            )
        except Exception as e:
            raise DatabaseConnectionException(
                f"Failed to initialize database engine: {str(e)}"
            ) from e

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def query(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        *,
        parse_dates: Sequence[str] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        try:
            stmt = text(sql)
        except Exception as e:
            raise InvalidQueryException(f"Failed to parse SQL query: {str(e)}") from e

        try:
            async with self._engine.connect() as conn:

                def _read_sync(sync_conn):
                    return pd.read_sql_query(
                        stmt,
                        con=sync_conn,
                        params=params,
                        parse_dates=parse_dates,
                    )

                df = await conn.run_sync(_read_sync)
                return df
        except SQLAlchemyError as e:
            error_msg = str(e).lower()
            print(f"SQL execution error: {str(e)}")
            print(f"SQL query: {sql}")

            # Classify the error type
            if "syntax" in error_msg or "parse" in error_msg:
                raise InvalidQueryException(
                    f"SQL syntax error: {str(e)}\nQuery: {sql[:500]}{'...' if len(sql) > 500 else ''}"
                ) from e
            elif (
                "permission" in error_msg
                or "denied" in error_msg
                or "privilege" in error_msg
            ):
                raise PermissionDeniedException(
                    f"Database permission denied: {str(e)}"
                ) from e
            elif "timeout" in error_msg or "timed out" in error_msg:
                raise QueryTimeoutException(
                    f"Query execution timed out: {str(e)}"
                ) from e
            elif "connection" in error_msg or "connect" in error_msg:
                raise DatabaseConnectionException(
                    f"Database connection error: {str(e)}"
                ) from e
            else:
                raise QueryExecutionException(
                    f"Query execution failed: {str(e)}\nQuery: {sql[:500]}{'...' if len(sql) > 500 else ''}"
                ) from e
        except Exception as e:
            print(f"Unexpected error during query execution: {str(e)}")
            raise QueryExecutionException(
                f"Unexpected error during query execution: {str(e)}"
            ) from e

    async def close(self) -> None:
        """Close the database engine and dispose of connection pool."""
        try:
            await self._engine.dispose()
        except Exception as e:
            raise DatabaseConnectionException(
                f"Failed to close database engine: {str(e)}"
            ) from e

    @classmethod
    def create_with_url(cls, url: str | URL, **engine_kwargs: Any) -> "SQLExecutor":
        try:
            engine = create_async_engine(url, **engine_kwargs)
            return cls(engine=engine)
        except Exception as e:
            raise DatabaseConnectionException(
                f"Failed to create SQL executor with URL: {str(e)}"
            ) from e
