def _normalize_relation_values(value):
    if value != value or value == "":
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def extract_containing_subject_matter(df, phrase):
    returner = df[df["subject_matter"].str.contains(phrase, na=False)]
    return returner


def get_df_with_celexes(df, celexes):
    returner = df[df["celex"].isin(celexes)]
    return returner


def get_edges_list(df, only_local):
    extraction = df[["celex", "citing"]]
    extraction.reset_index(inplace=True)
    keys = extraction["celex"].tolist()
    vals = extraction["citing"].tolist()
    nodes = set()
    edges = []
    local_keys = set(str(key) for key in keys)
    for k, val in zip(keys, vals):
        nodes.add(str(k))
        for target in _normalize_relation_values(val):
            if only_local and target not in local_keys:
                continue
            nodes.add(target)
            edge = str(k) + "," + target
            if edge not in edges:
                edges.append(edge)

    return edges, sorted(nodes)


def get_nodes_and_edges(df, only_local):
    edges, nodes = get_edges_list(df, only_local)
    # nodes = get_df_with_celexes(df,celexes)
    return nodes, edges
