"""
Hello World tool implementation.
"""


def execute(agent: dict, args: dict) -> dict:
    """
    Say hello to someone by name.

    Args:
        agent: Agent context dictionary
        args: Tool arguments containing 'name' parameter

    Returns:
        dict: Greeting response with status and message
    """
    name = args.get("name", "Guest")
    greeting = f"Hello, {name}! Welcome to the Hello World skill. 👋"
    return {
        "status": "success",
        "message": greeting,
        "greeting": greeting
    }
