"""Real backend implementation for the calculator tool."""


def execute(agent, args: dict) -> dict:
    expression = args.get("expression", "")
    allowed_chars = set("0123456789+-*/.() ")
    if not all(c in allowed_chars for c in expression):
        return {"error": "Invalid characters in expression"}
    try:
        result = eval(expression, {"__builtins__": {}})
        return {"result": result}
    except Exception as e:
        return {"error": f"Calculation error: {str(e)}"}


def test_execute():
    assert execute({}, {"expression": "2+2"}) == {"result": 4}
    assert execute({}, {"expression": "10 * 5"}) == {"result": 50}
    assert abs(execute({}, {"expression": "10/3"})["result"] - 3.3333) < 0.01
    assert "error" in execute({}, {"expression": "import os"})
    assert "error" in execute({}, {"expression": ""})
