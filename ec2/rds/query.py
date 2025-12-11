from typing import List, Dict, Tuple

def _validate_where_clause(where_clause: Dict):
    if "if" not in where_clause:
        raise ValueError("Where clause is missing an 'if'")
    elif "condition" not in where_clause:
        raise ValueError("Where clause is missing a 'condition'")

def build_query(
    base_query: str,
    base_params: List = [],
    where_clauses: List[Dict] = []
) -> Tuple[str, List]:
    query = base_query
    params = base_params.copy()

    where_conditions = []
    for where_clause in where_clauses:
        _validate_where_clause(where_clause)

        if where_clause["if"]:
            where_conditions.append(where_clause["condition"])

            if "param" in where_clause:
                params.append(where_clause["param"])

    if where_clauses:
        query += " WHERE " + " AND ".join(where_conditions)

    return query, params

        
            