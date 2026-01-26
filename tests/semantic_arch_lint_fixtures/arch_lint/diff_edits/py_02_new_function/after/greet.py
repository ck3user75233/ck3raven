def greet(name: str) -> str:
    return f"Hello, {name}"

# SUBSET EDIT: new public API function (NST-governed)
def greet_formal(title: str, name: str) -> str:
    return f"Good day, {title} {name}"
