---
name: What I could not see in my memory
about: You run an agent with a memory of its own. Tell us what it looks like and what you wanted the graph to answer.
title: "My memory: "
labels: memory
---

**What does your memory look like?**
Where it lives (SQLite, Postgres, Neo4j, JSON, a service…), roughly how many
nodes and links, and what the main node and link types are. A schema or a few
example rows help; personal data does not, please leave it out.

**What question did you want the graph to answer?**
"Which facts does my recall never reach", "why does the assistant believe
this", "what does it know about X", "what changed since last month"… whatever
you actually wanted to know.

**What did you try, and where did it stop?**
Did you get as far as a mapping? A viewer with the wrong shape? A tool that
answered the wrong thing? Nothing at all?

**Would you expose the graph contract from your memory server?**
Optional. `docs/graph-contract.md` proposes four tools. Which would you expose
tomorrow, which would you refuse to, and why?
