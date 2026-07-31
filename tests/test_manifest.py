from agentic_blanche.manifest import create_manifest


def test_manifest_records_configuration_and_tools(tmp_path):
    manifest = create_manifest(
        argv=("agentic-blanche", "search", "21", "21"),
        config={"edges": 21, "workers": 4},
        repository=tmp_path,
        plantri="missing-plantri",
        msolve="missing-msolve",
    )
    assert len(manifest["run_id"]) == 24
    assert manifest["config"]["edges"] == 21
    assert manifest["plantri"]["path"] == "missing-plantri"
    assert manifest["msolve"]["path"] == "missing-msolve"
