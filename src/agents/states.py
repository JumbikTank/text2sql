########################################################
# Show table
########################################################
# query -> VectorBase -> dict(id, table, distance, comment, full_desc, desc_cols)
# dict(id, table, distance, comment, full_desc, desc_cols) -> SQLCreator -> sql-query
# sql-query -> SQLExecutor -> pd.DataFrame
########################################################
# Create sql and Answer
########################################################
# query -> VectorBase -> dict(id, table, distance, comment, full_desc, desc_cols)
# dict(id, table, distance, comment, full_desc, desc_cols) -> SQLCreator -> sql-query
# sql-query -> SQLExecutor -> pd.DataFrame
# pd.DataFrame -> DataFrameToTextConverter -> text answer
########################################################
# Follow up:
########################################################
# dict(id, table, distance, comment, full_desc, desc_cols) | sql_query_prev -> SQLCreator -> sql-query
# sql-query -> SQLExecutor -> pd.DataFrame
# pd.DataFrame -> DataFrameToTextConverter -> text answer
########################################################


from typing import Any
from typing import Optional, Literal, Annotated
from operator import add, or_
from langgraph.graph import MessagesState


class AppState(MessagesState):
    tool_log: Annotated[list[dict[str, Any]], add]
    type: Optional[Literal["sql_query", "text_with_csv", "text"]] = None
    download_link: Annotated[dict[str, Any], or_] = {}
    sql_query: Optional[str] = None
    preview_data: Optional[str] = None
    no_tools_next: bool = False
