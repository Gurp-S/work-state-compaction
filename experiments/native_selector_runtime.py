"""Private, opt-in selector runtime; never applied to the native control."""
from pathlib import Path
import json

PROFILE='source_selector_minimal_v1'
FACTS={'component':'working_state_selection',
       'generation_scope':'selection_without_task_execution','semantic_status':'unverified'}


def configure(destination,profile):
    if profile!=PROFILE:raise ValueError('selector_runtime_profile_unregistered')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    instructions=destination/'selector-facts.json'
    instructions.write_text(json.dumps(FACTS),encoding='utf-8')
    return ['features.shell_tool=false','features.skip_host_skill_discovery=true',
            'model_instructions_file='+json.dumps(str(instructions.resolve())),
            'memories.use_memories=false','skills.max_context_tokens=1','features.apps=false']
