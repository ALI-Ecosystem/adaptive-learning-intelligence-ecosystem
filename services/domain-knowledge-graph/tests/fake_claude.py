"""A scripted stand-in for the Anthropic client, so the agent loop, the tools and the
evaluation can be tested without an API key. It is not a placement method."""
import json
from types import SimpleNamespace as NS


def _block_text(t):
    return NS(type="text", text=t)


def _block_tool(i, name, args):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=args)


class FakeMessages:
    def __init__(self):
        self.calls = 0

    def create(self, model, max_tokens, messages, system=None, tools=None):
        self.calls += 1
        usage = NS(input_tokens=100, output_tokens=20)
        if not tools:                                    # llm_only control
            return NS(content=[_block_text("Computer science")], usage=usage, stop_reason="end_turn")
        convo = messages[0]["content"]
        name = convo.split("we got to ")[1].split(" and I")[0] if "we got to " in convo else "tail recursion"
        last = messages[-1]["content"]
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step == 0:
            return NS(content=[_block_text("Searching."), _block_tool(1, "search_concepts", {"query": name, "k": 5})], usage=usage)
        result = json.loads(last[0]["content"]) if isinstance(last, list) and not last[0].get("is_error") else None
        if step == 1:
            if step == 1 and result:
                self.top = result[0]["id"]
            return NS(content=[_block_tool(2, "get_concept", {"id": self.top})], usage=usage)
        if step == 2:
            parents = result["parents"] if result else []
            parent = parents[0]["id"] if parents else self.top
            return NS(content=[_block_tool(3, "submit_placement", {
                "concept_name": name, "concept_name_original": name, "description": "test",
                "decision": "new", "parent_id": parent, "confidence": 0.5,
                "reasoning": "sibling of the top search hit (fake client)"})], usage=usage)
        raise AssertionError("fake client went past its script")


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()
