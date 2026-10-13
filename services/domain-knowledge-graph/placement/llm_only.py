"""Control: Claude with NO graph access, answering from memory only.

If this scores close to the agent, the agent's accuracy comes from the model having
memorised the taxonomy (Wikipedia / OpenAlex), not from exploring the graph.
"""
from . import config
from .graph import Graph

PROMPT = """In the OpenAlex / Microsoft Academic concept taxonomy, what is the direct parent \
concept of the concept below? Answer with the exact name of the parent concept only, nothing else.

Concept: {name}
Definition: {description}"""


def place_llm_only(graph: Graph, client, name: str, description: str | None,
                   model: str = config.CLAUDE_MODEL):
    # Room for the model to think before answering; the first SCRUM-89 run used 60 tokens
    # and got no text block back at all, so every answer was empty.
    resp = client.messages.create(model=model, max_tokens=1024, messages=[{
        "role": "user", "content": PROMPT.format(name=name, description=description or "-")}])
    answer = "".join(b.text for b in resp.content if b.type == "text").strip()
    answer = answer.splitlines()[-1].strip().strip('".*') if answer else ""
    matches = graph.find_by_name(answer) if answer else []
    return {"answer": answer, "parent_id": matches[0]["id"] if matches else None,
            "stop_reason": resp.stop_reason, "blocks": [b.type for b in resp.content],
            "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
