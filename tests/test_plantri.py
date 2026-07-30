from agentic_blanche.plantri import parse_plantri_ascii


def test_parse_plantri_tetrahedron():
    graph = parse_plantri_ascii("4 bcd,adc,abd,acb")
    assert graph.edge_count == 6
    assert graph.face_count == 4
