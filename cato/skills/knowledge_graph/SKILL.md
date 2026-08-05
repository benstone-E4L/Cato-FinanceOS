# Knowledge Graph Skill (Cognee)

## Overview
Pure SQLite recursive CTEs. Nodes from Mem0 facts. Edges from conversation
entities. Multi-hop relational queries.

## Depends On
- Skill 2 (Mem0) — the `facts` table must exist before this skill initialises.

## Node Types
- `person` — @mentions and named individuals
- `project` — project names
- `decision` — recorded decisions
- `file` — file paths (.py, .ts, .json, etc.)
- `concept` — CamelCase terms, ALL_CAPS identifiers, general concepts

## Edge Relation Types
- `co_mentioned` — two entities appeared in the same sentence
- `depends_on` — explicit dependency relationship
- `replaced_by` — superseded entity
- `caused_by` — causal relationship

<!-- COLD -->
## API

### Node Operations
```python
node_id = memory.add_node(type="person", label="alice", source_session="s1")
count   = memory.seed_nodes_from_facts(session_id="s1")
ids     = memory.extract_and_add_nodes(text="See config.py and MyServiceClass", session_id="s1")
```

### Edge Operations
```python
ok = memory.add_edge("alice", "config.py", relation_type="co_mentioned")
memory.extract_and_add_edges(text="alice edited config.py", session_id="s1")
```

### Multi-Hop Queries
```python
hops = memory.query_graph("alice", depth=3)
near = memory.related_concepts("alice", max_hops=2)
```

## CLI
```
cato graph query <label> [--depth 3]
cato graph related <label> [--max-hops 2]
```

## Tool Actions
- `graph.query`   — multi-hop traversal from a label
- `graph.related` — ranked neighbours within max_hops
