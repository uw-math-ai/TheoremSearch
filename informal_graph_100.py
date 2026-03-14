import pandas as pd
import igraph as ig
from pyvis.network import Network
from rds.utils.connect import get_rds_connection
import webbrowser

def fetch_statements():
    with get_rds_connection() as conn:
        return pd.read_sql("""
            SELECT statement_id, kind, body
            FROM statement
        """, conn)

def fetch_dependencies():
    with get_rds_connection() as conn:
        return pd.read_sql("""
            SELECT source_id, dep_id
            FROM dependency
        """, conn)

statements = fetch_statements()
deps = fetch_dependencies()

g = ig.Graph(directed=True)

# nodes
g.add_vertices(statements["statement_id"].astype(str).tolist())

# edges
edges = list(zip(
    deps["source_id"].astype(str),
    deps["dep_id"].astype(str)
))

g.add_edges(edges)

# attach metadata
stmt_map = statements.set_index("statement_id")

g.vs["kind"] = stmt_map["kind"].reindex(g.vs["name"]).tolist()
g.vs["body"] = stmt_map["body"].reindex(g.vs["name"]).tolist()

net = Network(height="900px", width="100%", directed=True)

for v in g.vs:
    net.add_node(
        v["name"],
        label=v["kind"],
        title=v["body"][:400] if v["body"] else "",
    )

for e in g.es:
    net.add_edge(
        g.vs[e.source]["name"],
        g.vs[e.target]["name"]
    )

net.barnes_hut()

net.write_html("dependency_graph.html")
webbrowser.open("dependency_graph.html")