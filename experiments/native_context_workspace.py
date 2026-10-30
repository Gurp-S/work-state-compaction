"""Explicit host/guest workspace proof; no rewriting of WSC store identities."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from wsc.contracts import require
from wsc.evidence import link_like


@dataclass(frozen=True)
class ContextWorkspace:
    host_root:str
    host_workspace:str
    guest_workspace:str
    marker:str
    marker_digest:str
    owner:str
    server:object

    @classmethod
    def prove(cls,session,core,actor_root):
        candidate=Path(actor_root).absolute()
        for part in (candidate,*candidate.parents):require(not link_like(part),'context_workspace_link')
        root=candidate.resolve(strict=True);host=(root/'actor').resolve(strict=True)
        require(str(host)==core.store.workspace,'context_host_workspace_mismatch')
        require(session.registration['workspace']=='/work/actor' and session.opened.get('cwd')=='/work/actor','context_guest_workspace_mismatch')
        name='.wsc-context-binding-'+uuid4().hex;marker=root/name;raw=uuid4().hex.encode()
        with marker.open('xb') as f:f.write(raw)
        expected=sha256(raw).hexdigest();guest='/work/'+name
        result=session.server.call('command/exec',dict(command=['/bin/sh','-c','pwd; sha256sum "$1"','probe',guest],
                                   cwd='/work/actor',timeoutMs=5000),timeout=10)
        require(result.get('exitCode')==0 and result.get('stdout','').splitlines()==['/work/actor',expected+'  '+guest],
                'context_workspace_mapping_unverified')
        return cls(str(root),str(host),'/work/actor',str(marker),expected,session.opened['thread']['id'],session.server)

    def validate(self,session,core):
        require(session.server is self.server and session.opened['thread']['id']==self.owner,'context_workspace_owner_changed')
        require(session.registration['workspace']==self.guest_workspace and session.opened.get('cwd')==self.guest_workspace,
                'context_guest_workspace_changed')
        require(core.store.workspace==self.host_workspace,'context_host_workspace_changed')
        try:
            root=Path(self.host_root)
            for part in (root,*root.parents):require(not link_like(part),'context_workspace_link')
            require(str((root/'actor').resolve(strict=True))==self.host_workspace and not link_like(self.marker),
                    'context_workspace_mapping_changed')
            with Path(self.marker).open('rb') as f:raw=f.read(65)
            require(sha256(raw).hexdigest()==self.marker_digest,'context_workspace_mapping_changed')
        except OSError:require(False,'context_workspace_mapping_unavailable')
