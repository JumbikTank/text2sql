import json
import re
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.tools.prompt_templates import SYSTEM_PROMPT_CONTROLLER


# Custom exceptions for SQL Controller
class SQLControllerException(Exception):
    """Base exception for SQL Controller errors"""

    pass


class ValidationException(SQLControllerException):
    """Exception raised when validation fails"""

    pass


class ResponseParseException(SQLControllerException):
    """Exception raised when LLM response cannot be parsed"""

    pass


class SQLController:
    """SQL query validator and corrector using LLM."""

    def __init__(self, *, chat_model: BaseChatModel) -> None:
        """
        Initialize SQL controller.

        Args:
            chat_model: BaseChatModel instance for LLM calls

        Note:
            For deterministic results, the chat_model should NOT have
            temperature, top_p, top_k, or seed in model_kwargs, as those
            will override parameters passed to ainvoke().
        """
        self.chat_model = chat_model

    async def control(
        self,
        *,
        sql_query: str,
        user_question: str,
        table_info: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """
        Validate and correct SQL query against user question and table information.

        This method validates the candidate SQL query and returns either:
        - The same SQL if it's correct and minimal
        - A corrected SQL that properly answers the user question
        - Empty string if the question cannot be answered with a read-only SELECT

        Args:
            sql_query: Candidate SQL query to validate (CANDIDATE SQL)
            user_question: Original user question
            table_info: Information about tables, columns, and relationships
            temperature: LLM temperature for validation (default: 0 for deterministic)
            max_tokens: Maximum tokens in response

        Returns:
            Validated or corrected SQL query string (or empty string if invalid)

        Raises:
            ValidationException: If validation process fails
            ResponseParseException: If LLM response cannot be parsed
        """
        prompt = self._build_prompt(
            sql_query=sql_query,
            user_question=user_question,
            table_info=table_info,
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_CONTROLLER),
            HumanMessage(content=prompt),
        ]

        try:
            resp = await self.chat_model.ainvoke(
                messages,
                
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise ValidationException(
                f"Failed to invoke LLM for SQL validation: {str(e)}"
            ) from e

        try:
            print(resp.content.strip())
            validated_sql = self._parse_response(resp.content.strip())
            return validated_sql
        except Exception as e:
            raise ResponseParseException(
                f"Failed to parse validation response: {str(e)}"
            ) from e

    @staticmethod
    def _build_prompt(
        *,
        sql_query: str,
        user_question: str,
        table_info: str,
    ) -> str:
        """
        Build prompt for LLM validation.

        Args:
            sql_query: Candidate SQL query to validate
            user_question: User's original question
            table_info: Table and column information with relationships

        Returns:
            Formatted prompt string
        """
        return f"""TABLES INFO:
{table_info}

USER QUESTION:
{user_question}

CANDIDATE SQL:
{sql_query}

Please validate and return the corrected SQL query in JSON format."""

    @staticmethod
    def _parse_response(response: str) -> str:
        """
        Parse LLM JSON response and extract SQL query.

        Args:
            response: Raw LLM response string

        Returns:
            Validated/corrected SQL query string (or empty string)

        Raises:
            ResponseParseException: If response cannot be parsed as valid JSON
        """

        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            response = json_match.group(0)

        try:
            result = json.loads(response)

            if "sql_query" not in result:
                raise ResponseParseException("Response missing 'sql_query' field")

            sql_query = result["sql_query"]

            if not isinstance(sql_query, str):
                raise ResponseParseException(
                    f"'sql_query' must be a string, got {type(sql_query)}"
                )

            return sql_query

        except json.JSONDecodeError as e:
            raise ResponseParseException(
                f"Failed to parse LLM response as JSON: {e}\nResponse: {response}"
            ) from e
