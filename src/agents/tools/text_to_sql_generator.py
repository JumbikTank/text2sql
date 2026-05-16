import json
from typing import Any

import pandas as pd
import sqlparse
from df_to_text_converter import DataFrameToTextConverter
from sql_executor import SQLExecutor
from langchain_core.language_models import BaseChatModel
from required_tables_searcher import VectorStore
from sql_creator import SQLCreator


# Custom exceptions for Text to SQL Generator
class TextToSQLException(Exception):
    """Base exception for Text to SQL Generator errors"""

    pass


class PipelineException(TextToSQLException):
    """Exception raised when pipeline execution fails"""

    pass


class NoContextException(TextToSQLException):
    """Exception raised when no previous context is available for follow-up"""

    pass


class TableSearchException(TextToSQLException):
    """Exception raised when table search fails"""

    pass


class SQLGenerationException(TextToSQLException):
    """Exception raised when SQL generation fails"""

    pass


class SQLParsingException(TextToSQLException):
    """Exception raised when SQL parsing fails"""

    pass


class SQLExecutionException(TextToSQLException):
    """Exception raised when SQL execution fails"""

    pass


class ResponseGenerationException(TextToSQLException):
    """Exception raised when response generation fails"""

    pass


class TextToSQLGenerator:
    def __init__(
        self,
        chat_model: BaseChatModel,
        store: VectorStore,
        sql_creator: SQLCreator,
        executor: SQLExecutor,
        df_to_text: DataFrameToTextConverter,
    ):
        self.chat_model = chat_model
        self.store = store
        self.sql_creator = sql_creator
        self.executor = executor
        self.df_to_text = df_to_text

        # Store previous query context for follow-up queries
        self.previous_context: dict[str, Any] | None = None

    async def _find_relevant_tables(
        self,
        user_query: str,
        model: str = "multilingual-e5-small",
        is_follow_up: bool = False,
    ) -> list:
        if is_follow_up and self.previous_context:
            print(
                f"Reusing tables from previous query: {[t['table'] for t in self.previous_context['tables_used']]}"
            )
            return self.previous_context["tables_used"]

        try:
            result = await self.store.search(query_text=user_query, model=model)
            print(
                f"Vector search found {len(result)} relevant tables: {[t['table'] for t in result]}"
            )
            if not result:
                raise TableSearchException(
                    "No relevant tables found for your query. Please try rephrasing."
                )
            return result
        except Exception as e:
            if isinstance(e, TableSearchException):
                raise
            raise TableSearchException(
                f"Failed to search for relevant tables: {str(e)}"
            ) from e

    async def _generate_sql(
        self,
        user_query: str,
        tables: list,
        is_follow_up: bool = False,
        max_tokens: int = 10000,
    ) -> str:
        try:
            if is_follow_up and self.previous_context:
                print("Generating follow-up SQL based on previous query")
                sql_query = await self.sql_creator.create_sql(
                    question=user_query,
                    list_tables=tables,
                    max_tokens=max_tokens,
                    follow_up=True,
                    sql_prev=self.previous_context["formatted_sql"],
                )
            else:
                print("Generating new SQL query")
                sql_query = await self.sql_creator.create_sql(
                    question=user_query, list_tables=tables, max_tokens=max_tokens
                )

            return sql_query
        except Exception as e:
            raise SQLGenerationException(
                f"Failed to generate SQL query: {str(e)}"
            ) from e

    def _parse_and_format_sql(self, sql_query: str) -> tuple[str, str]:
        # Try to parse JSON response
        try:
            try:
                sql = json.loads(sql_query)["sql_query"]
                print("Successfully parsed SQL from JSON response")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Could not parse JSON, treating as plain SQL: {e}")
                sql = sql_query

            # Validate SQL is not empty
            if not sql or not sql.strip():
                raise SQLParsingException("Generated SQL query is empty")

            # Format SQL for readability
            formatted_sql = sqlparse.format(sql, reindent=True, keyword_case="upper")

            return sql, formatted_sql
        except SQLParsingException:
            raise
        except Exception as e:
            raise SQLParsingException(
                f"Failed to parse and format SQL query: {str(e)}"
            ) from e

    async def _execute_sql(self, formatted_sql: str) -> pd.DataFrame:
        try:
            df = await self.executor.query(sql=formatted_sql)
            print(f"Query executed successfully, returned {len(df)} rows")

            if len(df) == 0:
                print("Warning: Query returned no results")

            return df
        except Exception as e:
            raise SQLExecutionException(f"Failed to execute SQL query: {str(e)}") from e

    async def _generate_natural_language_response(
        self,
        df: pd.DataFrame,
        user_query: str,
        tables: list,
        formatted_sql: str,
        temperature: float = 0.8,
        max_tokens: int = 50000,
    ) -> str:
        try:
            print("Generating natural language response")

            answer = await self.df_to_text.answer(
                df=df,
                user_question=user_query,
                list_tables=tables,
                sql=formatted_sql,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            print(
                f"Generated response: {answer[:100]}..."
                if len(answer) > 100
                else f"Generated response: {answer}"
            )
            return answer
        except Exception as e:
            raise ResponseGenerationException(
                f"Failed to generate natural language response: {str(e)}"
            ) from e

    def _update_context(
        self,
        user_query: str,
        sql: str,
        formatted_sql: str,
        tables: list,
        df: pd.DataFrame,
        answer: str,
    ) -> None:
        self.previous_context = {
            "user_query": user_query,
            "sql_query": sql,
            "formatted_sql": formatted_sql,
            "tables_used": tables,
            "dataframe": df,
            "answer": answer,
        }
        print("Context updated for potential follow-up queries")

    async def process_query(
        self,
        user_query: str,
        model: str = "multilingual-e5-small",
        is_follow_up: bool = False,
        temperature: float = 0.8,
        max_tokens: int = 50000,
    ) -> dict[str, Any]:
        try:
            print(
                f"\n=== Starting {'follow-up' if is_follow_up else 'new'} query pipeline ==="
            )
            print(f"User query: {user_query}")

            if is_follow_up and self.previous_context is None:
                raise NoContextException(
                    "No previous query context available for follow-up. "
                    "Please execute an initial query first."
                )

            # Step 1: Find relevant tables
            tables = await self._find_relevant_tables(user_query, model, is_follow_up)

            # Step 2: Generate SQL
            sql_query = await self._generate_sql(
                user_query, tables, is_follow_up, max_tokens=10000
            )

            # Step 3: Parse and format SQL
            sql, formatted_sql = self._parse_and_format_sql(sql_query)

            # Step 4: Execute SQL
            df = await self._execute_sql(formatted_sql)

            # Step 5: Generate natural language response
            answer = await self._generate_natural_language_response(
                df, user_query, tables, formatted_sql, temperature, max_tokens
            )

            # Step 6: Update context
            self._update_context(user_query, sql, formatted_sql, tables, df, answer)

            print("=== Pipeline completed successfully ===")

            return {
                "answer": answer,
                "sql_query": sql,
                "formatted_sql": formatted_sql,
                "dataframe": df,
                "tables_used": tables,
                "is_follow_up": is_follow_up,
            }

        except (
            NoContextException,
            TableSearchException,
            SQLGenerationException,
            SQLParsingException,
            SQLExecutionException,
            ResponseGenerationException,
        ):
            # Re-raise known exceptions
            raise
        except Exception as e:
            print(f"Error in pipeline: {str(e)}")
            import traceback

            print(f"Traceback: {traceback.format_exc()}")
            raise PipelineException(f"Pipeline execution failed: {str(e)}") from e

    async def text_to_sql(
        self, user_query: str, model: str = "multilingual-e5-small"
    ) -> str:
        result = await self.process_query(user_query, model)
        return result["answer"]

    async def get_sql_only(
        self,
        user_query: str,
        model: str = "multilingual-e5-small",
        is_follow_up: bool = False,
    ) -> dict[str, str]:
        try:
            tables = await self._find_relevant_tables(user_query, model, is_follow_up)

            sql_query = await self._generate_sql(user_query, tables, is_follow_up)

            sql, formatted_sql = self._parse_and_format_sql(sql_query)

            return {
                "sql_query": sql,
                "formatted_sql": formatted_sql,
                "tables_used": tables,
            }

        except (TableSearchException, SQLGenerationException, SQLParsingException):
            raise
        except Exception as e:
            print(f"Error in get_sql_only: {str(e)}")
            raise PipelineException(f"Failed to generate SQL: {str(e)}") from e

    async def follow_up_query(
        self, user_query: str, temperature: float = 0.8, max_tokens: int = 50000
    ) -> dict[str, Any]:
        return await self.process_query(
            user_query=user_query,
            is_follow_up=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def search_tables(
        self, user_query: str, model: str = "multilingual-e5-small"
    ) -> list:
        try:
            return await self._find_relevant_tables(
                user_query, model, is_follow_up=False
            )
        except TableSearchException:
            raise
        except Exception as e:
            raise TableSearchException(f"Table search failed: {str(e)}") from e

    async def generate_sql_from_tables(
        self, user_query: str, tables: list, max_tokens: int = 10000
    ) -> dict[str, str]:
        try:
            sql_query = await self._generate_sql(
                user_query, tables, is_follow_up=False, max_tokens=max_tokens
            )
            sql, formatted_sql = self._parse_and_format_sql(sql_query)

            return {"sql_query": sql, "formatted_sql": formatted_sql}
        except (SQLGenerationException, SQLParsingException):
            raise
        except Exception as e:
            raise PipelineException(
                f"Failed to generate SQL from tables: {str(e)}"
            ) from e

    async def execute_and_explain(
        self,
        sql: str,
        user_query: str,
        tables: list | None = None,
        temperature: float = 0.8,
        max_tokens: int = 50000,
    ) -> dict[str, Any]:
        try:
            formatted_sql = sqlparse.format(sql, reindent=True, keyword_case="upper")
            df = await self._execute_sql(formatted_sql)

            tables = tables or []
            answer = await self._generate_natural_language_response(
                df, user_query, tables, formatted_sql, temperature, max_tokens
            )

            return {"answer": answer, "dataframe": df, "formatted_sql": formatted_sql}
        except (SQLExecutionException, ResponseGenerationException):
            raise
        except Exception as e:
            raise PipelineException(
                f"Failed to execute and explain SQL: {str(e)}"
            ) from e

    def get_previous_context(self) -> dict[str, Any] | None:
        return self.previous_context

    def clear_context(self) -> None:
        self.previous_context = None
        print("Query context cleared")

    def has_previous_context(self) -> bool:
        return self.previous_context is not None

    def get_previous_sql(self) -> str | None:
        if self.previous_context:
            return self.previous_context["formatted_sql"]
        return None

    def get_previous_tables(self) -> list | None:
        if self.previous_context:
            return self.previous_context["tables_used"]
        return None

    def get_previous_dataframe(self) -> pd.DataFrame | None:
        if self.previous_context:
            return self.previous_context["dataframe"]
        return None

    async def simple_chat(self, user_query: str, temperature: float = 0.7) -> str:
        """
        Simple chat functionality without database interaction
        """
        from langchain_core.messages import HumanMessage

        try:
            message = HumanMessage(content=user_query)
            resp = await self.chat_model.ainvoke([message], temperature=temperature)
            return resp.content.strip()
        except Exception as e:
            print(f"Error in simple chat: {str(e)}")
            # Return error message for simple chat instead of raising
            return f"Sorry, I encountered an error: {str(e)}"
