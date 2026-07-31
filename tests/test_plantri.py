import shutil

from agentic_blanche.plantri import Plantri, parse_plantri_ascii


def test_parse_plantri_tetrahedron():
    graph = parse_plantri_ascii("4 bcd,adc,abd,acb")
    assert graph.edge_count == 6
    assert graph.face_count == 4
    if shutil.which("plantri"):
        live = next(Plantri().graphs(4, 6))
        assert live.edge_count == 6
        assert live.face_count == 4
