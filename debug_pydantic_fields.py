
from pydantic_ai import AgentRunResult

try:
    print(f"Dataclass fields: {AgentRunResult.__dataclass_fields__.keys()}")
except Exception as e:
    print(f"Not a dataclass or error: {e}")

# Check annotations just in case
try:
    print(f"Annotations: {AgentRunResult.__annotations__.keys()}")
except:
    pass
