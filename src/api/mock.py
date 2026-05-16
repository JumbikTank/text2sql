import random
from datetime import datetime

from litestar import Response, post
from litestar.status_codes import HTTP_200_OK

from src.common.dto import Message, MessagesRequest, SqlRequest
from src.common.logger import get_logger
from src.common.settings import Settings, get_settings

logger = get_logger(__name__)


def provide_settings() -> Settings:
    """Dependency provider for settings."""
    return get_settings()


@post("/mock/messages")
async def mock_send_messages(
    data: MessagesRequest,
    settings: Settings,
) -> Response[Message]:
    """Mock endpoint for sending messages and regenerating SQL."""
    logger.info(f"Mock: Received {len(data.messages)} messages")

    # Generate mock response based on last message
    last_message = data.messages[-1] if data.messages else None

    if last_message and "sql" in last_message.content.lower():
        # Return SQL response
        mock_sql = """```sql
SELECT 
    u.id,
    u.name,
    u.email,
    COUNT(o.id) as order_count,
    SUM(o.total_amount) as total_spent
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.created_at >= '2024-01-01'
GROUP BY u.id, u.name, u.email
ORDER BY total_spent DESC
LIMIT 10;
```"""

        response = Message(role="assistant", content=mock_sql, type="sql")
    else:
        # Return plain text response
        responses = [
            "Based on the data analysis, here are the key findings:\n\n1. **User engagement** has increased by 23% this quarter\n2. **Revenue growth** shows a positive trend of 15%\n3. **Customer satisfaction** remains high at 4.7/5",
            "I've analyzed your request. The database contains 1,543 users with 8,291 total orders. The average order value is $127.50.",
            "Processing complete. The query returned 42 results matching your criteria. The data shows a strong correlation between user activity and purchase frequency.",
        ]

        response = Message(
            role="assistant", content=random.choice(responses), type="plain"
        )

    # Log the full response data
    logger.info(f"Mock: Returning {response.type} response")
    logger.info("=== MOCK RESPONSE DATA ===")
    logger.info(f"Response object: {response}")
    logger.info(f"Response dict: {response.model_dump()}")
    logger.info(f"Response JSON: {response.model_dump_json()}")
    logger.info("=== END MOCK RESPONSE DATA ===")

    return Response(content=response, status_code=HTTP_200_OK)


@post("/mock/sql")
async def mock_execute_sql(
    data: SqlRequest,
    settings: Settings,
) -> Response[Message]:
    """Mock endpoint for SQL execution."""
    logger.info(f"Mock: Executing SQL query of length {len(data.sql)}")

    # Generate mock table data
    mock_table = """| id | name | email | order_count | total_spent |
|---|---|---|---|---|
| 1 | Alice Johnson | alice@example.com | 12 | 2,450.00 |
| 2 | Bob Smith | bob@example.com | 8 | 1,890.50 |
| 3 | Charlie Brown | charlie@example.com | 15 | 3,210.75 |
| 4 | Diana Ross | diana@example.com | 6 | 980.25 |
| 5 | Edward Norton | edward@example.com | 10 | 2,100.00 |

Query executed successfully. Retrieved 5 rows in 0.023 seconds."""

    # Generate filename for consistency
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results_{timestamp}.csv"

    response = Message(
        role="assistant",
        content=mock_table,
        type="plain",
        download_link=f"{settings.csv_download_base_url}/{filename}",
    )

    logger.info("Mock: SQL execution complete")

    # Log the full response data
    logger.info("=== MOCK SQL RESPONSE DATA ===")
    logger.info(f"Response object: {response}")
    logger.info(f"Response dict: {response.model_dump()}")
    logger.info(f"Response JSON: {response.model_dump_json()}")
    logger.info("=== END MOCK SQL RESPONSE DATA ===")

    return Response(content=response, status_code=HTTP_200_OK)


__all__ = [
    "mock_send_messages",
    "mock_execute_sql",
    "provide_settings",
]
