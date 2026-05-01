"""Real backend implementation for the get_current_date tool."""


def execute(agent, args: dict) -> dict:
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d, %A")
    return {"result": current_date}


def test_execute():
    result = execute({}, {})
    assert "result" in result
    assert isinstance(result["result"], str)
    # Format: "YYYY-MM-DD, DayName"
    parts = result["result"].split(", ")
    assert len(parts) == 2
    assert len(parts[0].split("-")) == 3
