from litestar import Response, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from src.agents.services import SqlService
from src.common.dto import Message, SqlRequest
from src.common.logger import get_logger
from src.common.settings import Settings, get_settings

logger = get_logger(__name__)


def provide_settings() -> Settings:
    return get_settings()


@post("/sql")
async def execute_sql(
    data: SqlRequest,
    settings: Settings,
) -> Response[Message]:
    from time import perf_counter

    start_time = perf_counter()
    logger.info("=== SQL API ENDPOINT START ===")
    logger.info(f"Received SQL request with query length: {len(data.sql)}")
    logger.info(f"SQL query preview: {data.sql[:200]}...")

    try:
        logger.info(f"Request data type: {type(data)}")
        logger.info(f"Settings type: {type(settings)}")
        logger.info(f"Database host: {settings.db_host}")
        logger.info(f"Database name: {settings.database}")
        logger.info(f"CSV export path: {settings.csv_export_path}")

        logger.info("Creating SqlService instance")
        service_start = perf_counter()
        service = SqlService(settings)
        service_creation_time = perf_counter() - service_start
        logger.info(f"SqlService created successfully in {service_creation_time:.3f}s")

        logger.info("Calling service.execute_sql")
        execution_start = perf_counter()
        response_message = await service.execute_sql(data.sql)
        execution_time = perf_counter() - execution_start
        logger.info(f"service.execute_sql completed in {execution_time:.3f}s")

        logger.info(f"Response message type: {type(response_message)}")
        logger.info(f"Response role: {response_message.role}")
        logger.info(f"Response type: {response_message.type}")
        logger.info(f"Response content length: {len(response_message.content)}")
        logger.info(f"Response content preview: {response_message.content[:200]}...")
        logger.info(f"Response download_link: {response_message.download_link}")

        logger.info("Creating Litestar Response object")
        api_response = Response(response_message)
        logger.info(f"Litestar Response created: {type(api_response)}")

        total_time = perf_counter() - start_time
        logger.info(f"=== SQL API ENDPOINT SUCCESS in {total_time:.3f}s ===")

        return api_response

    except ValueError as e:
        error_time = perf_counter() - start_time
        logger.warning(f"=== SQL VALIDATION ERROR after {error_time:.3f}s ===")
        logger.warning(f"Validation error: {str(e)}")
        logger.warning(f"Failed SQL query: {data.sql}")
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        error_time = perf_counter() - start_time
        logger.error(f"=== SQL API ENDPOINT ERROR after {error_time:.3f}s ===")
        logger.error(f"Error type: {type(e)}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Failed SQL query: {data.sql}")
        logger.exception("Full SQL API endpoint error traceback:")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL execution failed: {str(e)}",
        )


__all__ = [
    "execute_sql",
    "provide_settings",
]
