import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Any

from src.agents.tools.prompt_templates import SYSTEM_ANSWER_PROMPT


class DataFrameToTextConverter:
    def __init__(
        self,
        chat_model: BaseChatModel,
    ) -> None:
        self.chat_model = chat_model

    @staticmethod
    def _render_tables(list_tables: list[dict[str, Any]]) -> str:
        desc = ""
        for i, table in enumerate(list_tables, start=1):
            desc += f"{table['full_desc']}\n\n{table['desc_cols']}\n\n"
        return desc

    async def answer(
        self,
        df: pd.DataFrame,
        user_question: str,
        list_tables: list[dict[str, Any]],
        sql: str,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = 4096,
        stream: bool = False,
    ) -> str:
        desc = self._render_tables(list_tables)
        sys_msg = SystemMessage(content=SYSTEM_ANSWER_PROMPT)
        data_block = self._build_markdown_block(df)
        user_msg = HumanMessage(
            content=(
                "<USER_QUESTION>\n"
                f"{user_question}\n"
                f"</USER_QUESTION>\n\n"
                "<TABLE_MARKDOWN>\n"
                f"{data_block}\n"
                f"</TABLE_MARKDOWN>\n\n"
                "<SQL_QUERY>\n"
                f"{sql}\n"
                f"</SQL_QUERY>\n\n"
                "<SCHEMA>\n"
                f"{desc}\n"
                f"</SCHEMA>"
            ),
        )

        print(user_msg.content)

        try:
            # Use LangChain chat model with message format
            messages = [sys_msg, user_msg]

            if stream:
                # Handle streaming case
                response_text = ""
                async for chunk in self.chat_model.astream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    response_text += chunk.content
                response_text = response_text.strip()
            else:
                resp = await self.chat_model.ainvoke(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                response_text = resp.content.strip()

            if not response_text:
                return "Unable to generate response from the query results."

            return response_text

        except Exception as e:
            print(f"Error generating natural language response: {str(e)}")
            try:
                if not df.empty:
                    row_count = len(df)
                    col_count = len(df.columns)
                    return f"Query executed successfully. Found {row_count} rows and {col_count} columns of data."
                else:
                    return "Query executed successfully but returned no results."
            except Exception:
                return "Query completed but unable to generate detailed response."

    def _build_markdown_block(self, df: pd.DataFrame) -> str:
        try:
            if df.empty:
                return "No data available in query results."

            table_md = df.to_markdown(index=False)
            return table_md

        except ImportError:
            error_msg = (
                "Missing 'tabulate' package required for DataFrame markdown conversion. "
                "Install with: pip install tabulate"
            )
            print(f"Error: {error_msg}")
            return f"Query Results (tabulate not available):\n{str(df)}"
        except Exception as e:
            print(f"Error converting DataFrame to markdown: {e}")
            return f"Query Results:\n{str(df)}"
