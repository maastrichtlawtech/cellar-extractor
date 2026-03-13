from SPARQLWrapper import SPARQLWrapper, JSON, CSV, POST
import requests


def _query_with_retries(sparql, retries, error_message):
    last_error = None
    for _ in range(retries):
        try:
            return sparql.queryAndConvert()
        except Exception as exc:
            last_error = exc
    raise RuntimeError(error_message) from last_error


def _build_citation_relations_query(celexes, cites_depth=1, cited_depth=1):
    if cites_depth < 0 or cited_depth < 0:
        raise ValueError("Citation depths must be non-negative")

    input_celex = '", "'.join(celexes)
    subqueries = []
    if cites_depth > 0:
        subqueries.append(
            """
            SELECT ?celex ?citedD ?direction WHERE {
                ?doc cdm:resource_legal_id_celex ?celex .
                FILTER(STR(?celex) in ("%s")) .
                ?doc cdm:work_cites_work{1,%i} ?cited .
                ?cited cdm:resource_legal_id_celex ?citedD .
                BIND("outbound" AS ?direction)
            }
            """
            % (input_celex, cites_depth)
        )
    if cited_depth > 0:
        subqueries.append(
            """
            SELECT ?celex ?citedD ?direction WHERE {
                ?doc cdm:resource_legal_id_celex ?celex .
                FILTER(STR(?celex) in ("%s")) .
                ?cited cdm:work_cites_work{1,%i} ?doc .
                ?cited cdm:resource_legal_id_celex ?citedD .
                BIND("inbound" AS ?direction)
            }
            """
            % (input_celex, cited_depth)
        )

    if not subqueries:
        raise ValueError("At least one citation depth must be greater than zero")

    return """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT * WHERE {
            %s
        }
    """ % " UNION ".join("{%s}" % subquery for subquery in subqueries)


def _build_citation_query(source_celex, cites_depth, cited_depth):
    if cites_depth < 0 or cited_depth < 0:
        raise ValueError("Citation depths must be non-negative")

    subqueries = []
    if cites_depth > 0:
        subqueries.append(
            """
            SELECT ?name2 WHERE {
                ?doc cdm:resource_legal_id_celex "%s"^^xsd:string .
                ?doc cdm:work_cites_work{1,%i} ?cited .
                ?cited cdm:resource_legal_id_celex ?name2 .
            }
            """
            % (source_celex, cites_depth)
        )
    if cited_depth > 0:
        subqueries.append(
            """
            SELECT ?name2 WHERE {
                ?doc cdm:resource_legal_id_celex "%s"^^xsd:string .
                ?cited cdm:work_cites_work{1,%i} ?doc .
                ?cited cdm:resource_legal_id_celex ?name2 .
            }
            """
            % (source_celex, cited_depth)
        )

    if not subqueries:
        raise ValueError("At least one citation depth must be greater than zero")

    return """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT * WHERE {
            %s
        }
    """ % " UNION ".join("{%s}" % subquery for subquery in subqueries)


def _extract_citation_targets(result):
    targets = set()
    for bind in result["results"]["bindings"]:
        target = bind["name2"]["value"]
        targets.add(target)
    return targets


def run_eurlex_webservice_query(query_input, username, password):
    target = "https://eur-lex.europa.eu/EURLexWebService?wsdl"
    query = """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:sear="http://eur-lex.europa.eu/search">
      <soap:Header>
        <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" soap:mustUnderstand="true">
          <wsse:UsernameToken xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" wsu:Id="UsernameToken-1">
            <wsse:Username>%s</wsse:Username>
            <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">%s</wsse:Password>
          </wsse:UsernameToken>
        </wsse:Security>
      </soap:Header>
      <soap:Body>
        <sear:searchRequest>
          <sear:expertQuery><![CDATA[%s]]></sear:expertQuery>
          <sear:page>1</sear:page>
          <sear:pageSize>100</sear:pageSize>
          <sear:searchLanguage>en</sear:searchLanguage>
        </sear:searchRequest>
      </soap:Body>
    </soap:Envelope>""" % (
        username,
        password,
        query_input,
    )
    return requests.request("POST", target, data=query, allow_redirects=True)


def get_citations(source_celex, cites_depth=1, cited_depth=1, max_retries=3):
    """
    Method acquired from a different law and tech project
    for getting the citations of a
    source_celex.
    Unlike get_citations_csv, only works for one source celex at once.
    Returns a set containing all the works cited by the source celex.
    Gets all the citations one to X steps away. Hops can be specified as either
    the source document citing another (defined by `cites_depth`)
    or another document
    citing it (`cited_depth`). Any numbers higher than 1 denote that
    new source document
    citing a document of its own.

    This specific implementation does not care about intermediate steps,
    it simply finds
    anything X or fewer hops away without linking those together.
    """
    sparql = SPARQLWrapper("https://publications.europa.eu/webapi/rdf/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setQuery(_build_citation_query(source_celex, cites_depth, cited_depth))
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to fetch citations after retries",
    )
    # Filters the list. Filter type: '3'=legislation, '6'=case law.
    targets = _extract_citation_targets(ret)
    targets = set([el for el in list(targets)])
    return targets


def get_citations_csv(celex, max_retries=3):
    """
    Method sending a query to the endpoint,
    which asks for cited works for each celex.
    The celex variable in the method is a list of
    all the celex identifiers of the
    cases we need the citations of.
    The query returns a csv, containing all of the data needed."""
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    input_celex = '", "'.join(celex)
    query = """
           prefix cdm: <http://publications.europa.eu/ontology/cdm#>
 prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT * WHERE
        {
        {
            SELECT ?celex ?citedD WHERE {
                ?doc cdm:resource_legal_id_celex ?celex
                 FILTER(STR(?celex) in ("%s")).
                ?doc cdm:work_cites_work{1,1} ?cited .
                ?cited cdm:resource_legal_id_celex ?citedD .
            }
        } UNION {
            SELECT ?celex ?citedD WHERE {
                ?doc cdm:resource_legal_id_celex ?celex
                 FILTER(STR(?celex) in ("%s")).
                ?cited cdm:work_cites_work{1,1} ?doc .
                ?cited cdm:resource_legal_id_celex ?citedD .
            }
        }
}
       """ % (
        input_celex,
        input_celex,
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(CSV)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to fetch citations CSV after retries",
    )
    return ret.decode("utf-8")


def get_citation_relations_csv(celex, cites_depth=1, cited_depth=1, max_retries=3):
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    query = _build_citation_relations_query(
        celex,
        cites_depth=cites_depth,
        cited_depth=cited_depth,
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(CSV)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to fetch citation relations after retries",
    )
    return ret.decode("utf-8")


def get_citing(celex, cites_depth, max_retries=3):
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    input_celex = '", "'.join(celex)
    query = """
           prefix cdm: <http://publications.europa.eu/ontology/cdm#>
 prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT * WHERE
        {
            SELECT ?celex ?citedD WHERE {
                ?doc cdm:resource_legal_id_celex ?celex
                 FILTER(STR(?celex) in ("%s")).
                ?doc cdm:work_cites_work{1,%i} ?cited .
                ?cited cdm:resource_legal_id_celex ?citedD .
            }
}
       """ % (
        input_celex,
        cites_depth,
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(CSV)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to fetch citing cases after retries",
    )
    return ret.decode("utf-8")


def get_cited(celex, cited_depth, max_retries=3):
    endpoint = "https://publications.europa.eu/webapi/rdf/sparql"
    input_celex = '", "'.join(celex)
    query = """
           prefix cdm: <http://publications.europa.eu/ontology/cdm#>
 prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT * WHERE
        {
            SELECT ?celex ?citedD WHERE {
                ?doc cdm:resource_legal_id_celex ?celex
                 FILTER(STR(?celex) in ("%s")).
                ?cited cdm:work_cites_work{1,%i} ?doc .
                ?cited cdm:resource_legal_id_celex ?citedD .
            }
}
       """ % (
        input_celex,
        cited_depth,
    )

    sparql = SPARQLWrapper(endpoint)
    sparql.setReturnFormat(CSV)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    ret = _query_with_retries(
        sparql,
        retries=max_retries,
        error_message="Failed to fetch cited cases after retries",
    )
    return ret.decode("utf-8")
