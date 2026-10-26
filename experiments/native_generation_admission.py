"""Read-only discovery and retained native generation threads, without retry."""
from pathlib import Path

from native_evidence import save
from native_group_admission import NativeGroupAdmission
from native_pair_admission import observe
from run_native_pair import MODEL, import_items
from wsc.contracts import encode, require


def admit(server, reg, area, opened):
    require(reg.get("orchestration") == "retained_generation_group_v1"
            and reg.get("admission_warmup_threads") == 1, "generation_admission_not_registered")
    controls = [{"type": "message", "role": "assistant", "content": [{"type": "output_text",
        "text": encode({"kind": "generation_admission", "study": area.name})}]}]
    plugins = server.call("plugin/list", {"cwds": [reg["workspace"]], "forceRefetch": False}, timeout=45)
    skills = server.call("skills/list", {"cwds": [reg["workspace"]], "forceReload": False}, timeout=45)
    save(area / "discovery.json", {"plugins": plugins, "skills": skills})
    require(not plugins.get("marketplaceLoadErrors"), "native_plugin_discovery_failed")
    for name in ["warmup", *reg["order"]]:
        cell = area / "admission" / name
        cell.mkdir(parents=True, exist_ok=False)
        value = server.call("thread/start", {"cwd": reg["workspace"], "model": MODEL,
            "allowProviderModelFallback": False, "approvalPolicy": "never", "sandbox": "read-only",
            "runtimeWorkspaceRoots": [reg["workspace"]], "ephemeral": False, "dynamicTools": []}, timeout=40)
        opened[name] = value
        save(cell / "thread-start.json", value)
        require(value["model"] == MODEL and value.get("reasoningEffort") == "max"
                and value["sandbox"]["type"] == "readOnly", "frontier_native_configuration_changed")
        import_items(server, value, controls, cell)
        if name == "warmup":
            observed = observe(value, controls)
            save(cell / "observation.json", observed)
            require(observed["response_count"] == 0, "warmup_inference_detected")
    observations = lambda: {name: observe(opened[name], controls) for name in reg["order"]}
    initial = observations()
    save(area / "generation-admission-observations.json", initial)
    gate = NativeGroupAdmission(initial, members=reg["order"])
    save(area / "generation-admission.json", {"admitted": True, "new_model_responses": 0,
         "members": {name: value["thread_id"] for name, value in initial.items()},
         "native_prompt_or_plugin_changes": False})
    return gate, observations
