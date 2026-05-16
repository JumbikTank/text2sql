from typing import Any
from datetime import datetime


from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import Table, MetaData, Column, select, func, desc, text

NUMERIC_MARKERS = (
    "INT",
    "INTEGER",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "DECIMAL",
    "NUMERIC",
    "FLOAT",
    "DOUBLE",
    "REAL",
)
DATE_MARKERS = ("DATE", "DATETIME", "TIMESTAMP", "TIME", "YEAR")
CATEGORICAL_MARKERS = (
    "CHAR",
    "VARCHAR",
    "TEXT",
    "TINYTEXT",
    "MEDIUMTEXT",
    "LONGTEXT",
    "ENUM",
    "SET",
)
VECTOR_MARKERS = ("VECTOR",)


class MySQLTableProfiler:
    def __init__(self, dsn: str, schema: str | None = None) -> None:
        self.engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True)
        self.schema = schema
        self.table_name: str | None = None

    async def _get_columns_info(self, conn, table_name: str) -> list[dict[str, Any]]:
        if self.schema is None:
            where_schema = "TABLE_SCHEMA = DATABASE()"
            params = {"table_name": table_name}
        else:
            where_schema = "TABLE_SCHEMA = :schema"
            params = {"schema": self.schema, "table_name": table_name}

        sql = text(f"""
            SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE {where_schema} AND TABLE_NAME = :table_name
            ORDER BY ORDINAL_POSITION
        """)
        rows = (await conn.execute(sql, params)).mappings().all()
        return [
            {
                "name": r["COLUMN_NAME"],
                "data_type": (r["DATA_TYPE"] or "").upper(),
                "column_type": (r["COLUMN_TYPE"] or "").upper(),
            }
            for r in rows
        ]

    async def profile_table(self, table_name: str, top_k: int = 10) -> dict[str, Any]:
        self.table_name = table_name

        async with self.engine.connect() as conn:
            cols_meta = await self._get_columns_info(conn, table_name)
            if not cols_meta:
                raise ValueError(
                    f"Таблица не найдена или нет доступа: {self.schema or '(current DB)'}.{table_name}"
                )

            md = MetaData(schema=self.schema)
            tbl = Table(table_name, md, schema=self.schema)
            for c in cols_meta:
                tbl.append_column(Column(c["name"]))

            out: dict[str, Any] = {"table": table_name, "columns": {}}

            for c in cols_meta:
                colname = c["name"]
                data_type = c["data_type"]
                column_type = c["column_type"]
                dtype = column_type or data_type

                col = tbl.c[colname]

                if any(marker in data_type for marker in NUMERIC_MARKERS):
                    if "ID" in colname.upper() or "INDEX" in colname.upper():
                        continue
                    stmt = select(
                        func.min(col).label("min"),
                        func.max(col).label("max"),
                    ).select_from(tbl)
                    row = (await conn.execute(stmt)).one()

                    out["columns"][colname] = {
                        "min": row.min,
                        "max": row.max,
                    }

                elif any(marker in data_type for marker in DATE_MARKERS):
                    stmt = select(
                        func.min(col).label("min"),
                        func.max(col).label("max"),
                    ).select_from(tbl)
                    row = (await conn.execute(stmt)).one()

                    out["columns"][colname] = {
                        "min": row.min,
                        "max": row.max,
                    }

                elif any(marker in data_type for marker in CATEGORICAL_MARKERS):
                    distinct_stmt = select(
                        func.count(func.distinct(col)).label("distinct")
                    ).select_from(tbl)
                    distinct_val = (await conn.execute(distinct_stmt)).scalar_one()

                    if distinct_val > 50:
                        continue
                    else:
                        topk_stmt = (
                            select(col.label("value"), func.count().label("cnt"))
                            .select_from(tbl)
                            .where(col.is_not(None))
                            .group_by(col)
                            .order_by(desc("cnt"))
                            .limit(top_k)
                        )
                        topk_rows = (await conn.execute(topk_stmt)).all()

                        values = [r.value for r in topk_rows]

                        out["columns"][colname] = {
                            "unique_values": values,
                        }

                elif any(marker in data_type for marker in VECTOR_MARKERS):
                    total_stmt = select(
                        func.count().label("count_all"),
                        (func.count() - func.count(col)).label("nulls"),
                    ).select_from(tbl)
                    row = (await conn.execute(total_stmt)).one()

                    dim = None
                    import re

                    m = re.search(r"VECTOR\((\d+)\)", dtype)
                    if m:
                        dim = int(m.group(1))

                    out["columns"][colname] = {
                        "type": dtype,
                        "class": "vector",
                        "dimension": dim,
                        "count_all": int(row.count_all),
                        "nulls": int(row.nulls),
                    }

                else:
                    total_stmt = select(
                        func.count().label("count_all"),
                        (func.count() - func.count(col)).label("nulls"),
                    ).select_from(tbl)
                    row = (await conn.execute(total_stmt)).one()
                    out["columns"][colname] = {}

            return out

    async def format_profile(self, profile: dict, max_values: int = None) -> str:
        lines = []
        for col, info in profile.items():
            lines.append(f"Column: {col}")
            if "min" in info and "max" in info:
                min_val = info["min"]
                max_val = info["max"]
                if isinstance(min_val, datetime):
                    min_val = min_val.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(max_val, datetime):
                    max_val = max_val.strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"  Min: {min_val}")
                lines.append(f"  Max: {max_val}")
            if "unique_values" in info:
                vals = info["unique_values"]
                if max_values is not None and len(vals) > max_values:
                    shown = vals[:max_values]
                    lines.append(
                        f"  Unique values (first {max_values} from {len(vals)}):"
                    )
                    for v in shown:
                        lines.append(f"    - {v}")
                else:
                    lines.append("  Unique values:")
                    for v in vals:
                        lines.append(f"    - {v}")
            lines.append("")
        return "\n".join(lines)
