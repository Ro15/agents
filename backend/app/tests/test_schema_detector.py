import pandas as pd

from app.schema_detector import detect_schema


def test_detect_schema_handles_mixed_object_values_for_bounds():
    df = pd.DataFrame({"mixed": ["alpha", 2, "10", None]})

    schemas = detect_schema(df)

    assert len(schemas) == 1
    schema = schemas[0]
    assert schema.pg_type == "TEXT"
    assert schema.min_value == "10"
    assert schema.max_value == "alpha"

