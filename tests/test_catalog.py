import json
from pathlib import Path
import pytest
from automation.catalog import CapabilityCatalog
from tests.fakes import checkout_artifact


def _dir(tmp_path):
    art = checkout_artifact()
    (tmp_path / f"{art.name}.json").write_text(art.model_dump_json(indent=2))
    return tmp_path


def _write(path, artifact):
    path.write_text(artifact.model_dump_json(indent=2))


def test_catalog_lists_capabilities_by_name(tmp_path):
    catalog = CapabilityCatalog(_dir(tmp_path))
    assert [c["name"] for c in catalog.list()] == ["prepare_product_checkout"]


def test_listing_exposes_the_derivation_of_a_reviewed_artifact(tmp_path):
    artifact = checkout_artifact(provenance="hand_authored", derived_from="discovery-abc")
    (tmp_path / "c.json").write_text(artifact.model_dump_json())
    assert CapabilityCatalog(tmp_path).list()[0]["derived_from"] == "discovery-abc"


def test_tool_schema_exposes_typed_inputs(tmp_path):
    schema = CapabilityCatalog(_dir(tmp_path)).tool_schema("prepare_product_checkout")
    props = schema["input_schema"]["properties"]
    assert props["quantity"]["type"] == "integer"
    assert props["quantity"]["minimum"] == 1
    assert props["product"]["maxLength"] == 80
    assert set(schema["input_schema"]["required"]) == {"email", "password",
                                                       "product", "quantity"}


def test_tool_schema_marks_sensitive_inputs_without_carrying_values(tmp_path):
    schema = CapabilityCatalog(_dir(tmp_path)).tool_schema("prepare_product_checkout")
    assert schema["input_schema"]["properties"]["password"]["writeOnly"] is True
    assert "hunter2" not in json.dumps(schema)


def test_tool_schema_documents_outputs_and_business_outcomes(tmp_path):
    schema = CapabilityCatalog(_dir(tmp_path)).tool_schema("prepare_product_checkout")
    assert "product_name" in schema["description"]
    assert "session_expired" in schema["description"]


def test_tool_schema_describes_an_empty_output_contract_as_none(tmp_path):
    artifact = checkout_artifact(outputs={})
    _write(tmp_path / f"{artifact.name}.json", artifact)

    description = CapabilityCatalog(tmp_path).tool_schema(artifact.name)["description"]

    assert "Returns: none." in description
    assert "Returns: ." not in description


def test_tool_schema_includes_unique_step_and_artifact_outcomes_in_order(tmp_path):
    art = checkout_artifact()
    art.business_outcomes.append(art.steps[2].business_outcomes[0])
    _write(tmp_path / f"{art.name}.json", art)

    schema = CapabilityCatalog(tmp_path).tool_schema(art.name)

    assert "Known business outcomes: product_not_found, session_expired." in schema["description"]


def test_catalog_lists_capabilities_sorted_by_name(tmp_path):
    _write(tmp_path / "a.json", checkout_artifact(name="zeta_capability"))
    _write(tmp_path / "z.json", checkout_artifact(name="alpha_capability"))

    assert [c["name"] for c in CapabilityCatalog(tmp_path).list()] == [
        "alpha_capability", "zeta_capability"
    ]


def test_catalog_rejects_duplicate_capability_names(tmp_path):
    _write(tmp_path / "first.json", checkout_artifact(name="same_capability"))
    _write(tmp_path / "second.json", checkout_artifact(name="same_capability"))

    with pytest.raises(ValueError, match="duplicate.*same_capability"):
        CapabilityCatalog(tmp_path).list()


def test_unknown_capability_raises(tmp_path):
    with pytest.raises(KeyError):
        CapabilityCatalog(_dir(tmp_path)).get("nope")


def test_checked_artifacts_match_the_approved_capability_contracts():
    catalog = CapabilityCatalog(Path(__file__).parents[1] / "evidence" / "artifacts")
    register = catalog.get("register_test_account")
    checkout = catalog.get("prepare_product_checkout")
    deletion = catalog.get("delete_test_account")

    assert set(register.outputs) == {"account_created"}
    assert {outcome.code for outcome in register.business_outcomes} == {
        "email_already_registered",
    }
    assert checkout.inputs["quantity"].min_value == 1
    assert set(checkout.outputs) == {"product_name", "unit_price", "cart_total"}
    assert {
        outcome.code
        for outcome in [
            *checkout.business_outcomes,
            *(outcome for step in checkout.steps for outcome in step.business_outcomes),
        ]
    } == {"product_not_found", "authentication_failed", "session_expired"}
    assert set(deletion.inputs) == {"email", "password"}
    assert set(deletion.outputs) == {"account_deleted"}
    assert "cancelled_by_human" in catalog.tool_schema("delete_test_account")["description"]
