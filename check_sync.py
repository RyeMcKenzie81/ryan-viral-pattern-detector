
from pydantic_ai import Agent
print(f"Agent methods: {dir(Agent)}")
try:
    agent = Agent('test')
    print(f"Has run_sync: {hasattr(agent, 'run_sync')}")
except:
    pass
