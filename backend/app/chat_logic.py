import re
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta

def get_last_updated(db: Session):
    # This function is not implemented yet.
    # It will be implemented in the main.py file.
    pass

def get_total_sales_yesterday(db: Session):
    sql = "SELECT SUM(total_line_amount) FROM sales_transactions WHERE DATE(order_datetime) = CURRENT_DATE - 1;"
    result = db.execute(text(sql)).scalar()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "number",
        "answer": result if result else 0,
        "explanation": "Total sales from yesterday.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_total_sales_last_7_days(db: Session):
    sql = "SELECT SUM(total_line_amount) FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days';"
    result = db.execute(text(sql)).scalar()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "number",
        "answer": result if result else 0,
        "explanation": "Total sales from the last 7 days.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_daily_sales_trend_last_14_days(db: Session):
    sql = "SELECT DATE(order_datetime) as date, SUM(total_line_amount) as total_sales FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '14 days' GROUP BY DATE(order_datetime) ORDER BY date;"
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Daily sales trend for the last 14 days.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_top_5_selling_items_by_revenue(db: Session):
    sql = "SELECT item_name, SUM(total_line_amount) as total_revenue FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days' GROUP BY item_name ORDER BY total_revenue DESC LIMIT 5;"
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Top 5 selling items by revenue this week.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_top_5_selling_items_by_quantity(db: Session):
    sql = "SELECT item_name, SUM(quantity) as total_quantity FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days' GROUP BY item_name ORDER BY total_quantity DESC LIMIT 5;"
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Top 5 selling items by quantity this week.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_worst_5_selling_items_this_week(db: Session):
    sql = "SELECT item_name, SUM(quantity) as total_quantity FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days' GROUP BY item_name ORDER BY total_quantity ASC LIMIT 5;"
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Worst 5 selling items by quantity this week.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_sales_by_hour_for_yesterday(db: Session):
    sql = "SELECT EXTRACT(HOUR FROM order_datetime) as hour, SUM(total_line_amount) as total_sales FROM sales_transactions WHERE DATE(order_datetime) = CURRENT_DATE - 1 GROUP BY hour ORDER BY hour;"
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Sales by hour for yesterday.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_category_growth_wow(db: Session):
    # This query is a bit more complex. It requires comparing two weeks.
    # For simplicity, we'll define 'this week' as the last 7 days and 'last week' as the 7 days before that.
    sql = """
    WITH weekly_sales AS (
        SELECT
            category,
            CASE
                WHEN order_datetime >= CURRENT_DATE - INTERVAL '7 days' THEN 'this_week'
                WHEN order_datetime >= CURRENT_DATE - INTERVAL '14 days' AND order_datetime < CURRENT_DATE - INTERVAL '7 days' THEN 'last_week'
            END AS week,
            SUM(total_line_amount) as total_sales
        FROM sales_transactions
        WHERE category IS NOT NULL AND order_datetime >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY category, week
    )
    SELECT
        this_week.category,
        this_week.total_sales as this_week_sales,
        last_week.total_sales as last_week_sales,
        (this_week.total_sales - last_week.total_sales) / last_week.total_sales * 100 as growth_percentage
    FROM weekly_sales this_week
    JOIN weekly_sales last_week ON this_week.category = last_week.category
    WHERE this_week.week = 'this_week' AND last_week.week = 'last_week'
    ORDER BY growth_percentage DESC;
    """
    result = db.execute(text(sql)).fetchall()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(row) for row in result],
        "explanation": "Week-over-week growth by category.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_avg_order_value_last_7_days(db: Session):
    sql = "SELECT AVG(order_total) FROM (SELECT order_id, SUM(total_line_amount) as order_total FROM sales_transactions WHERE order_datetime >= CURRENT_DATE - INTERVAL '7 days' GROUP BY order_id) as order_summary;"
    result = db.execute(text(sql)).scalar()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "number",
        "answer": result if result else 0,
        "explanation": "Average order value for the last 7 days.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }

def get_sales_comparison_this_vs_last_week(db: Session):
    sql = """
    SELECT
        SUM(CASE WHEN order_datetime >= CURRENT_DATE - INTERVAL '7 days' THEN total_line_amount ELSE 0 END) as this_week_sales,
        SUM(CASE WHEN order_datetime >= CURRENT_DATE - INTERVAL '14 days' AND order_datetime < CURRENT_DATE - INTERVAL '7 days' THEN total_line_amount ELSE 0 END) as last_week_sales
    FROM sales_transactions
    WHERE order_datetime >= CURRENT_DATE - INTERVAL '14 days';
    """
    result = db.execute(text(sql)).fetchone()
    last_updated = get_last_updated(db)
    return {
        "answer_type": "table",
        "answer": [dict(result)],
        "explanation": "Comparison of total sales between this week and last week.",
        "sql": sql,
        "data_last_updated": last_updated,
        "confidence": "high"
    }


# Rule-based routing
question_router = {
    r"total sales yesterday": get_total_sales_yesterday,
    r"total sales last 7 days": get_total_sales_last_7_days,
    r"daily sales trend last 14 days": get_daily_sales_trend_last_14_days,
    r"top 5 selling items this week by revenue": get_top_5_selling_items_by_revenue,
    r"top 5 selling items this week by quantity": get_top_5_selling_items_by_quantity,
    r"worst 5 selling items this week": get_worst_5_selling_items_this_week,
    r"sales by hour for yesterday": get_sales_by_hour_for_yesterday,
    r"category is growing week-over-week": get_category_growth_wow,
    r"average order value for last 7 days": get_avg_order_value_last_7_days,
    r"compare this week vs last week total sales": get_sales_comparison_this_vs_last_week,
}

def route_question(query: str, db: Session):
    for pattern, handler in question_router.items():
        if re.search(pattern, query, re.IGNORECASE):
            return handler(db)
    return {
        "answer_type": "text",
        "answer": "I can't answer that question yet. Please try one of the supported questions.",
        "explanation": "The query did not match any of the supported questions.",
        "sql": None,
        "data_last_updated": get_last_updated(db),
        "confidence": "low"
    }
